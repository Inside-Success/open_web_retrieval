"""Disk-based caching for search results and fetched pages.

Prevents re-fetching during iterative investigation loops where the agent
revisits the same queries or URLs across planning cycles. Cache entries are
keyed by normalized query/URL and expire after a configurable TTL.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _file_lock(path: Path) -> Generator[None, None, None]:
    """Advisory file lock for concurrent cache access.

    Uses fcntl.flock on Unix. On platforms without fcntl (Windows),
    degrades to a no-op — callers still get correct single-process behavior.
    """
    if not _HAS_FCNTL:
        yield
        return

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


@dataclass
class CacheStats:
    """Snapshot of cache state and counters."""

    entries: int = 0
    size_bytes: int = 0
    hits: int = 0
    misses: int = 0
    evictions: int = 0


class DiskCache:
    """Simple disk-backed JSON cache with TTL expiration.

    Each entry is stored as a JSON file named by the SHA-256 of the cache key.
    A metadata wrapper stores the timestamp and TTL for expiration checks.
    Supports optional max-entry LRU eviction and advisory file locking.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        default_ttl_seconds: int = 3600,
        max_entries: int = 10_000,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_seconds = default_ttl_seconds
        self.max_entries = max_entries

        # Counters — instance-level, reset on new DiskCache instance
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    def _key_path(self, key: str) -> Path:
        """Derive a filesystem path from a cache key."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        """Return cached value if present and not expired, else None."""
        path = self._key_path(key)

        with _file_lock(path):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                self._misses += 1
                logger.debug("CACHE_MISS key=%s", key[:40])
                return None
            except (json.JSONDecodeError, OSError):
                self._misses += 1
                logger.debug("CACHE_MISS key=%s (read error)", key[:40])
                return None

        stored_at = data.get("stored_at", 0)
        ttl = data.get("ttl", self.default_ttl_seconds)
        if time.time() - stored_at > ttl:
            path.unlink(missing_ok=True)
            self._misses += 1
            logger.debug("CACHE_MISS key=%s (expired)", key[:40])
            return None

        self._hits += 1
        logger.debug("CACHE_HIT key=%s", key[:40])
        return data.get("value")

    def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        """Store a JSON-serializable value with TTL."""
        logger.debug("CACHE_SET key=%s", key[:40])
        path = self._key_path(key)
        envelope = {
            "key": key,
            "value": value,
            "stored_at": time.time(),
            "ttl": ttl if ttl is not None else self.default_ttl_seconds,
        }
        with _file_lock(path):
            path.write_text(json.dumps(envelope, default=str), encoding="utf-8")

        self._enforce_max_entries()

    def _enforce_max_entries(self) -> None:
        """Evict oldest entries (by mtime) if cache exceeds max_entries."""
        entries = list(self.cache_dir.glob("*.json"))
        excess = len(entries) - self.max_entries
        if excess <= 0:
            return

        # Sort by modification time ascending (oldest first)
        entries.sort(key=lambda p: p.stat().st_mtime)
        for path in entries[:excess]:
            path.unlink(missing_ok=True)
            self._evictions += 1
            logger.debug("CACHE_EVICT path=%s", path.name)

    def clear(self) -> int:
        """Remove all cache entries. Returns count of entries removed."""
        count = 0
        for path in self.cache_dir.glob("*.json"):
            path.unlink(missing_ok=True)
            count += 1
        return count

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count of entries evicted."""
        count = 0
        now = time.time()
        for path in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if now - data.get("stored_at", 0) > data.get("ttl", self.default_ttl_seconds):
                    path.unlink(missing_ok=True)
                    count += 1
                    self._evictions += 1
            except (json.JSONDecodeError, OSError):
                path.unlink(missing_ok=True)
                count += 1
                self._evictions += 1
        return count

    def stats(self) -> CacheStats:
        """Return a snapshot of cache size and hit/miss/eviction counters."""
        entries = list(self.cache_dir.glob("*.json"))
        size_bytes = sum(p.stat().st_size for p in entries)
        return CacheStats(
            entries=len(entries),
            size_bytes=size_bytes,
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
        )
