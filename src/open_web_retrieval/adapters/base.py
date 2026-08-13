"""Shared abstractions for search-provider adapters."""

from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from open_web_retrieval.models import SearchHit, SearchQuery

# Default limits apply only to keyless providers whose public-service usage
# guidance calls for client-side pacing. Paid providers retain their existing
# behavior unless a consumer explicitly configures an override.
_PROVIDER_LIMITS: dict[str, tuple[int, int]] = {
    "hackernews": (120, 4),
    "arxiv": (18, 1),
    # OpenAlex semantic search is limited to one request per second. Use the
    # same conservative ceiling for all OpenAlex modes so callers can switch
    # modes without bypassing the provider's narrowest public-service limit.
    "openalex": (60, 1),
    # Measured ceiling is roughly 100/min; retain substantial headroom.
    "reddit": (60, 2),
}


def provider_limits(provider: str) -> tuple[int, int]:
    """Return effective requests-per-minute and concurrency for ``provider``.

    Operators may override the conservative defaults without changing code.
    Invalid values fail back to the declared defaults so a malformed optional
    tuning variable cannot take retrieval down.
    """

    rpm_default, concurrency_default = _PROVIDER_LIMITS.get(provider, (0, 4))
    try:
        rpm = int(os.environ.get(f"OWR_RPM_{provider.upper()}", rpm_default))
    except ValueError:
        rpm = rpm_default
    try:
        concurrency = int(
            os.environ.get(
                f"OWR_CONCURRENCY_{provider.upper()}",
                concurrency_default,
            ),
        )
    except ValueError:
        concurrency = concurrency_default
    return max(0, rpm), max(1, concurrency)


class ProviderThrottle:
    """Thread-safe request-start pacing shared by sync search adapters.

    Clock and sleep callables are injectable so tests can prove pacing without
    wall-clock delays. Async callers run synchronous adapters in a worker
    thread, preventing this deliberately blocking primitive from stalling an
    event loop.
    """

    def __init__(
        self,
        provider: str,
        *,
        requests_per_minute: int | None = None,
        max_concurrent: int | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        default_rpm, default_concurrency = provider_limits(provider)
        rpm = default_rpm if requests_per_minute is None else requests_per_minute
        concurrency = default_concurrency if max_concurrent is None else max_concurrent
        self.provider = provider
        self.min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._semaphore = threading.Semaphore(max(1, concurrency))
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self._monotonic = monotonic
        self._sleep = sleep

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Wait for a provider slot, then hold its concurrency permit."""

        self._semaphore.acquire()
        try:
            if self.min_interval:
                with self._lock:
                    wait_seconds = self._next_allowed - self._monotonic()
                    if wait_seconds > 0:
                        self._sleep(wait_seconds)
                    self._next_allowed = self._monotonic() + self.min_interval
            yield
        finally:
            self._semaphore.release()


_THROTTLES: dict[str, ProviderThrottle] = {}
_THROTTLES_LOCK = threading.Lock()


def throttle_for(provider: str) -> ProviderThrottle:
    """Return the process-wide throttle shared by one provider."""

    with _THROTTLES_LOCK:
        if provider not in _THROTTLES:
            _THROTTLES[provider] = ProviderThrottle(provider)
        return _THROTTLES[provider]


def reset_provider_throttles() -> None:
    """Reset cached throttles after configuration changes, primarily in tests."""

    with _THROTTLES_LOCK:
        _THROTTLES.clear()


class SearchAdapter(ABC):
    """Abstract contract each search provider adapter must satisfy."""

    provider_name: str

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute provider search and return normalized hits."""

    @contextmanager
    def paced(self) -> Iterator[None]:
        """Hold this adapter's provider slot around one outbound request."""

        throttle = getattr(self, "_provider_throttle", None)
        with (throttle or throttle_for(self.provider_name)).hold():
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
