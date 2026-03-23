"""Shared abstractions for search-provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from open_web_retrieval.models import SearchHit, SearchQuery


class SearchAdapter(ABC):
    """Abstract contract each search provider adapter must satisfy."""

    provider_name: str

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute provider search and return normalized hits."""


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
