"""Disk-based caching for search results and fetched pages.

Prevents re-fetching during iterative investigation loops where the agent
revisits the same queries or URLs across planning cycles. Cache entries are
keyed by normalized query/URL and expire after a configurable TTL.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class DiskCache:
    """Simple disk-backed JSON cache with TTL expiration.

    Each entry is stored as a JSON file named by the SHA-256 of the cache key.
    A metadata wrapper stores the timestamp and TTL for expiration checks.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        default_ttl_seconds: int = 3600,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_seconds = default_ttl_seconds

    def _key_path(self, key: str) -> Path:
        """Derive a filesystem path from a cache key."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        """Return cached value if present and not expired, else None."""
        path = self._key_path(key)
        if not path.exists():
            logger.debug("CACHE_MISS key=%s", key[:40])
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("CACHE_MISS key=%s", key[:40])
            return None

        stored_at = data.get("stored_at", 0)
        ttl = data.get("ttl", self.default_ttl_seconds)
        if time.time() - stored_at > ttl:
            path.unlink(missing_ok=True)
            logger.debug("CACHE_MISS key=%s", key[:40])
            return None
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
        path.write_text(json.dumps(envelope, default=str), encoding="utf-8")

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
            except (json.JSONDecodeError, OSError):
                path.unlink(missing_ok=True)
                count += 1
        return count
