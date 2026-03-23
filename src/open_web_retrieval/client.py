"""Public orchestrator for shared open-web retrieval workflows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from open_web_retrieval.adapters.base import SearchAdapter, SearchAdapterFactory
from open_web_retrieval.adapters.brave import BraveSearchAdapter
from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter
from open_web_retrieval.cache import DiskCache
from open_web_retrieval.exceptions import OpenWebRetrievalError, ProviderUnavailableError
from open_web_retrieval.fetch_extract import SourceFetcher
from open_web_retrieval.models import ExtractedDocument, FetchRequest, SearchHit, SearchQuery, SourceRecord


@dataclass(frozen=True)
class SourceRecordBatch:
    """Container for one retrieval run and its aggregate metadata."""

    query: SearchQuery
    records: list[SourceRecord]


class OpenWebRetrievalClient:
    """Shared facade for search, fetch, render, and extraction in v0."""

    def __init__(
        self,
        *,
        brave_api_key: str | None = None,
        searxng_base_url: str | None = None,
        timeout_seconds: float | None = None,
        adapters: Mapping[str, SearchAdapter] | None = None,
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        """Configure provider adapters, fetcher, and optional disk cache.

        Args:
            cache_dir: If set, enables disk-based caching for search and fetch.
                Search results cached by query+provider. Fetched pages cached by URL.
            cache_ttl_seconds: TTL for cache entries (default 1 hour).
        """
        configured_adapters: list[SearchAdapter] = []
        if adapters is not None:
            configured_adapters.extend(adapters.values())
        else:
            if brave_api_key:
                configured_adapters.append(BraveSearchAdapter(api_key=brave_api_key, timeout_seconds=timeout_seconds))
            if searxng_base_url:
                configured_adapters.append(
                    SearxNGSearchAdapter(base_url=searxng_base_url, timeout_seconds=timeout_seconds),
                )

        if not configured_adapters:
            raise ProviderUnavailableError(
                "no search providers configured",
                context={"reason": "provide brave_api_key and/or searxng_base_url"},
            )

        self.adapters = SearchAdapterFactory(list(configured_adapters))
        self.fetcher = SourceFetcher(timeout_seconds=timeout_seconds)
        self.default_providers = tuple(self.adapters.adapters.keys())

        self._search_cache: DiskCache | None = None
        self._fetch_cache: DiskCache | None = None
        if cache_dir is not None:
            cache_path = Path(cache_dir)
            self._search_cache = DiskCache(cache_path / "search", default_ttl_seconds=cache_ttl_seconds)
            self._fetch_cache = DiskCache(cache_path / "fetch", default_ttl_seconds=cache_ttl_seconds)

    def _search_cache_key(self, query: SearchQuery, provider: str) -> str:
        """Build a deterministic cache key for a search query + provider."""
        return f"search:{provider}:{query.query}:top_k={query.top_k}:recency={query.recency_days}"

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute search across requested providers and merge normalized hits."""
        providers = tuple(query.providers) if query.providers else self.default_providers
        if not providers:
            raise ProviderUnavailableError(
                "query has no providers",
                context={"query": query.query},
            )

        combined_hits: list[SearchHit] = []
        missing: list[str] = []
        failures: list[str] = []

        for provider in providers:
            # Check cache first
            if self._search_cache is not None:
                cache_key = self._search_cache_key(query, provider)
                cached = self._search_cache.get(cache_key)
                if cached is not None:
                    combined_hits.extend(SearchHit(**h) for h in cached)
                    continue

            adapter = self.adapters.get(provider)
            if adapter is None:
                missing.append(provider)
                continue
            try:
                hits = adapter.search(query)
                combined_hits.extend(hits)
                # Store in cache
                if self._search_cache is not None and hits:
                    cache_key = self._search_cache_key(query, provider)
                    self._search_cache.set(cache_key, [h.model_dump(mode="json") for h in hits])
            except OpenWebRetrievalError as exc:
                failures.append(f"{provider}: {exc.error_code}")
            except Exception as exc:  # pragma: no cover - defensive hard fail
                raise RuntimeError(f"unhandled provider exception for {provider}") from exc

        if not combined_hits:
            if missing:
                raise ProviderUnavailableError(
                    "all requested providers were unavailable",
                    context={"query": query.query, "missing": missing, "failures": failures},
                )
            raise OpenWebRetrievalError(
                "search returned no results",
                context={"query": query.query, "failures": failures},
            )
        return combined_hits[: query.top_k]

    def retrieve(
        self,
        query: SearchQuery,
        *,
        fetch_request: FetchRequest | None = None,
        allow_partial: bool = False,
    ) -> SourceRecordBatch:
        """Execute search + fetch + extract for a deterministic output batch."""
        hits = self.search(query)
        request = fetch_request or FetchRequest(url="")
        records: list[SourceRecord] = []

        for hit in hits:
            per_hit_fetch = FetchRequest(
                url=hit.url,
                render_mode=request.render_mode,
                user_agent_profile=request.user_agent_profile,
                max_bytes=request.max_bytes,
            )
            try:
                # Check fetch cache by URL
                cached_text = None
                if self._fetch_cache is not None:
                    cached_text = self._fetch_cache.get(f"fetch:{hit.url}")

                if cached_text is not None:
                    extracted = ExtractedDocument(**cached_text)
                    provenance = {
                        "provider": hit.provider,
                        "provider_query": query.query,
                        "cache": "hit",
                    }
                    records.append(
                        SourceRecord(
                            query=query.query,
                            search_hit=hit,
                            extracted_document=extracted,
                            provenance=provenance,
                        )
                    )
                else:
                    fetched = self.fetcher.fetch(per_hit_fetch)
                    extracted = self.fetcher.extract(fetched)
                    provenance = {
                        "provider": hit.provider,
                        "provider_query": query.query,
                    }
                    # Cache the extracted document
                    if self._fetch_cache is not None:
                        self._fetch_cache.set(
                            f"fetch:{hit.url}",
                            extracted.model_dump(mode="json"),
                        )
                    records.append(
                        SourceRecord(
                            query=query.query,
                            search_hit=hit,
                            fetched_resource=fetched,
                            extracted_document=extracted,
                            provenance=provenance,
                        )
                    )
            except Exception as exc:
                if not allow_partial:
                    raise
                records.append(
                    SourceRecord(
                        query=query.query,
                        search_hit=hit,
                        provenance={
                            "provider": hit.provider,
                            "provider_query": query.query,
                            "error": str(exc),
                            "error_type": exc.__class__.__name__,
                        },
                    )
                )

        return SourceRecordBatch(query=query, records=records)
