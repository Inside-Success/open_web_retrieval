"""Shared abstractions for search-provider adapters."""

from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager

from open_web_retrieval.models import SearchHit, SearchQuery

# ── Per-provider pacing ──────────────────────────────────────────────────────
# WHY THIS LIVES HERE (2026-07-28). ``rate_limit_per_second`` on the client
# paces PAGE FETCHES per domain, inside async_fetch. Search adapters each hold
# their own httpx.Client and never touch it, so every keyless provider was
# unpaced: the hackernews adapter had no limit at all and the arxiv adapter had
# a DOCSTRING saying "pacing belongs to the caller", which is a note, not a
# guard. Putting one throttle in the base class means a new adapter cannot
# silently skip it, and the numbers live in one readable table.
#
# The API-key providers (brave/tavily/exa) are deliberately absent: their
# ceilings are a billing matter between you and the vendor, and adding an
# unrequested delay to a paid call would be a surprise. Only providers we hit
# on someone else's goodwill are paced by default.
#
# (requests_per_minute, max_concurrent). RPM of 0 disables pacing.
_PROVIDER_LIMITS: dict[str, tuple[int, int]] = {
    # MEASURED 2026-07-28: Reddit sent x-ratelimit-remaining 998 of 1000 with a
    # 546s reset window, i.e. ~1000 requests per 10 minutes.
    # 60/min, NOT 100/min: 100 is exactly the 10-minute average, so sustaining
    # it leaves zero headroom and any burst trips the window. 60 gives ~40%
    # slack, and the engine only issues 14-28 queries per run anyway.
    "reddit": (60, 2),
    # HN Algolia publishes no hard limit and is generous in practice.
    "hackernews": (120, 4),
    # arXiv ASKS for roughly one request every three seconds, and asks not to be
    # hit concurrently. Serialized deliberately - this one is a courtesy
    # obligation to a free academic service, not a technical ceiling.
    "arxiv": (18, 1),
}


def provider_limits(provider: str) -> tuple[int, int]:
    """Effective (rpm, concurrency) for a provider, env-overridable.

    ``OWR_RPM_REDDIT=40`` / ``OWR_CONCURRENCY_ARXIV=2`` override the table so an
    operator who trips a limit can react without a code change.
    """
    rpm_default, conc_default = _PROVIDER_LIMITS.get(provider, (0, 4))
    try:
        rpm = int(os.environ.get(f"OWR_RPM_{provider.upper()}", rpm_default))
    except ValueError:
        rpm = rpm_default
    try:
        conc = int(os.environ.get(f"OWR_CONCURRENCY_{provider.upper()}", conc_default))
    except ValueError:
        conc = conc_default
    return rpm, max(1, conc)


class _Throttle:
    """Concurrency cap plus minimum spacing between request starts.

    Threading primitives, not asyncio: ``SearchAdapter.search`` is synchronous
    and adapters are called from both sync and async consumers. One lock keeps
    the spacing honest whichever thread arrives.
    """

    def __init__(self, provider: str) -> None:
        rpm, concurrency = provider_limits(provider)
        self.provider = provider
        self.min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._sem = threading.Semaphore(concurrency)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    @contextmanager
    def hold(self):
        """Block until this provider may start another request."""
        self._sem.acquire()
        try:
            if self.min_interval:
                with self._lock:
                    wait = self._next_allowed - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    self._next_allowed = time.monotonic() + self.min_interval
            yield
        finally:
            self._sem.release()


_THROTTLES: dict[str, _Throttle] = {}
_THROTTLES_LOCK = threading.Lock()


def throttle_for(provider: str) -> _Throttle:
    """Process-wide throttle for a provider (created once, shared thereafter)."""
    with _THROTTLES_LOCK:
        if provider not in _THROTTLES:
            _THROTTLES[provider] = _Throttle(provider)
        return _THROTTLES[provider]


def reset_throttles() -> None:
    """Drop cached throttles so env overrides re-read. Tests only."""
    with _THROTTLES_LOCK:
        _THROTTLES.clear()


class SearchAdapter(ABC):
    """Abstract contract each search provider adapter must satisfy."""

    provider_name: str

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute provider search and return normalized hits."""

    @contextmanager
    def paced(self):
        """Hold this provider's rate-limit slot for the duration of a request.

        Wrap the HTTP call, not the whole ``search`` body - normalization is
        free and should not occupy a slot other callers are waiting for.
        """
        with throttle_for(self.provider_name).hold():
            yield


class SearchAdapterFactory:
    """Utility for resolving adapters by canonical provider name."""

    def __init__(self, adapters: list[SearchAdapter]) -> None:
        """Store adapters in a stable provider-name index."""
        self._adapters = {adapter.provider_name: adapter for adapter in adapters}

    @property
    def adapters(self) -> dict[str, SearchAdapter]:
        """Return the provider-name-indexed adapter map."""
        return self._adapters

    def get(self, provider_name: str) -> SearchAdapter | None:
        """Resolve a provider adapter by name."""
        return self._adapters.get(provider_name)
