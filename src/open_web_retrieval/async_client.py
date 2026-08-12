"""Async orchestrator mirroring the sync OpenWebRetrievalClient API."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from pathlib import Path

from open_web_retrieval.adapters.base import SearchAdapter, SearchAdapterFactory
from open_web_retrieval.adapters.brave import BraveSearchAdapter
from open_web_retrieval.adapters.openalex import OpenAlexSearchAdapter
from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter
from open_web_retrieval.async_fetch import AsyncSourceFetcher
from open_web_retrieval.cache import DiskCache
from open_web_retrieval.client import SourceRecordBatch
from open_web_retrieval.exceptions import (
    OpenWebRetrievalError,
    ProviderUnavailableError,
)
from open_web_retrieval.models import (
    ExtractedDocument,
    FetchRequest,
    SearchHit,
    SearchQuery,
    SourceRecord,
)
from open_web_retrieval.observability import (
    ToolCallLogger,
    compact_query_target,
    duration_ms,
    emit_tool_call,
    make_tool_call_id,
    query_sha256,
    utc_now_iso,
)
from open_web_retrieval.search_log import SearchLog

logger = logging.getLogger(__name__)


class AsyncOpenWebRetrievalClient:
    """Async facade for search, fetch, and extraction.

    Search adapters are synchronous (fast, negligible I/O) so they run
    inline.  Fetch uses ``AsyncSourceFetcher`` for non-blocking HTTP.
    """

    def __init__(
        self,
        *,
        brave_api_key: str | None = None,
        searxng_base_url: str | None = None,
        enable_openalex: bool = False,
        openalex_api_key: str | None = None,
        timeout_seconds: float | None = None,
        adapters: Mapping[str, SearchAdapter] | None = None,
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: int = 3600,
        blocked_domains: set[str] | None = None,
        rate_limit_per_second: float = 2.0,
        tool_call_logger: ToolCallLogger | None = None,
        enable_auto_render: bool = True,
        search_log_path: str | Path | None = None,
    ) -> None:
        """Configure provider adapters, async fetcher, and optional disk cache.

        Args:
            brave_api_key: API key for Brave Search.
            searxng_base_url: Base URL for a SearxNG instance.
            timeout_seconds: Per-request timeout.
            adapters: Pre-built adapter mapping (overrides key-based config).
            cache_dir: If set, enables disk-based caching for search and fetch.
            cache_ttl_seconds: TTL for cache entries (default 1 hour).
            blocked_domains: Domain names to reject immediately.
            rate_limit_per_second: Max requests/s per domain. 0 disables.
            tool_call_logger: Optional observability logger.
            enable_auto_render: Detect JS-rendered SPAs and extract embedded JSON.
        """
        configured_adapters: list[SearchAdapter] = []
        if adapters is not None:
            configured_adapters.extend(adapters.values())
        else:
            if brave_api_key:
                configured_adapters.append(
                    BraveSearchAdapter(
                        api_key=brave_api_key, timeout_seconds=timeout_seconds,
                    ),
                )
            if searxng_base_url:
                configured_adapters.append(
                    SearxNGSearchAdapter(
                        base_url=searxng_base_url, timeout_seconds=timeout_seconds,
                    ),
                )
            if enable_openalex:
                configured_adapters.append(
                    OpenAlexSearchAdapter(
                        api_key=openalex_api_key,
                        timeout_seconds=timeout_seconds or 15.0,
                    )
                )

        if not configured_adapters:
            raise ProviderUnavailableError(
                "no search providers configured",
                context={"reason": "provide brave_api_key, searxng_base_url, or enable_openalex"},
            )

        self.adapters = SearchAdapterFactory(list(configured_adapters))
        self.fetcher = AsyncSourceFetcher(
            timeout_seconds=timeout_seconds,
            blocked_domains=blocked_domains,
            rate_limit_per_second=rate_limit_per_second,
            tool_call_logger=tool_call_logger,
            enable_auto_render=enable_auto_render,
        )
        self.default_providers = tuple(self.adapters.adapters.keys())
        self.tool_call_logger = tool_call_logger
        self._search_log: SearchLog | None = SearchLog(search_log_path) if search_log_path is not None else None

        self._search_cache: DiskCache | None = None
        self._fetch_cache: DiskCache | None = None
        if cache_dir is not None:
            cache_path = Path(cache_dir)
            self._search_cache = DiskCache(
                cache_path / "search", default_ttl_seconds=cache_ttl_seconds,
            )
            self._fetch_cache = DiskCache(
                cache_path / "fetch", default_ttl_seconds=cache_ttl_seconds,
            )

    def _search_cache_key(self, query: SearchQuery, provider: str) -> str:
        """Build a deterministic cache key for a search query + provider."""
        return (
            "search:"
            f"{provider}:{query.query}:top_k={query.top_k}:recency={query.recency_days}"
            f":depth={query.search_depth}:detail={query.result_detail}:budget={query.detail_budget}"
            f":corpus={query.corpus}:mode={getattr(query, 'mode', None)}"
            f":allow={','.join(query.domains_allow)}:deny={','.join(query.domains_deny)}"
        )

    async def search(
        self,
        query: SearchQuery,
        *,
        trace_id: str | None = None,
        task: str | None = None,
    ) -> list[SearchHit]:
        """Execute search across requested providers and merge normalized hits.

        Search adapters are synchronous (fast HTTP) so they run inline
        without wrapping in an executor.
        """
        providers = (
            tuple(query.providers) if query.providers else self.default_providers
        )
        if not providers:
            raise ProviderUnavailableError(
                "query has no providers",
                context={"query": query.query},
            )

        logger.info(
            "SEARCH query=%r providers=%s", query.query, ",".join(providers),
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
                    logger.debug(
                        "SEARCH_CACHE_HIT provider=%s query=%r",
                        provider,
                        query.query,
                    )
                    combined_hits.extend(SearchHit(**h) for h in cached)
                    continue

            adapter = self.adapters.get(provider)
            if adapter is None:
                missing.append(provider)
                continue

            call_id = make_tool_call_id()
            started_at = utc_now_iso()
            _needs_timing = self.tool_call_logger is not None or self._search_log is not None
            started_monotonic = time.monotonic() if _needs_timing else None
            common_metrics = {
                "query_sha256": query_sha256(query.query),
                "top_k": query.top_k,
            }
            emit_tool_call(
                self.tool_call_logger,
                call_id=call_id,
                tool_name="open_web_retrieval",
                operation="search",
                provider=provider,
                target=compact_query_target(query.query),
                status="started",
                started_at=started_at,
                attempt=1,
                task=task,
                trace_id=trace_id,
                metrics=common_metrics,
            )
            try:
                hits = adapter.search(query)
                combined_hits.extend(hits)
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=call_id,
                    tool_name="open_web_retrieval",
                    operation="search",
                    provider=provider,
                    target=compact_query_target(query.query),
                    status="succeeded",
                    started_at=started_at,
                    ended_at=utc_now_iso(),
                    duration_ms_value=(
                        duration_ms(started_monotonic)
                        if started_monotonic is not None
                        else None
                    ),
                    attempt=1,
                    task=task,
                    trace_id=trace_id,
                    metrics={**common_metrics, "returned_count": len(hits)},
                )
                # Store in cache
                if self._search_cache is not None and hits:
                    cache_key = self._search_cache_key(query, provider)
                    self._search_cache.set(
                        cache_key, [h.model_dump(mode="json") for h in hits],
                    )
                if self._search_log is not None:
                    self._search_log.log_search(
                        timestamp=started_at,
                        query=query.query,
                        provider=provider,
                        num_results=len(hits),
                        latency_ms=duration_ms(started_monotonic) if started_monotonic is not None else None,
                        trace_id=trace_id,
                        task=task,
                        top_sources=[h.url for h in hits[:5]],
                    )
            except OpenWebRetrievalError as exc:
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=call_id,
                    tool_name="open_web_retrieval",
                    operation="search",
                    provider=provider,
                    target=compact_query_target(query.query),
                    status="failed",
                    started_at=started_at,
                    ended_at=utc_now_iso(),
                    duration_ms_value=(
                        duration_ms(started_monotonic)
                        if started_monotonic is not None
                        else None
                    ),
                    attempt=1,
                    task=task,
                    trace_id=trace_id,
                    metrics=common_metrics,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
                if self._search_log is not None:
                    self._search_log.log_search(
                        timestamp=started_at,
                        query=query.query,
                        provider=provider,
                        latency_ms=duration_ms(started_monotonic) if started_monotonic is not None else None,
                        trace_id=trace_id,
                        task=task,
                        error=f"{exc.__class__.__name__}: {exc}",
                    )
                failures.append(f"{provider}: {exc.error_code}")
            except Exception as exc:  # pragma: no cover - defensive hard fail
                raise RuntimeError(
                    f"unhandled provider exception for {provider}",
                ) from exc

        if not combined_hits:
            if missing:
                raise ProviderUnavailableError(
                    "all requested providers were unavailable",
                    context={
                        "query": query.query,
                        "missing": missing,
                        "failures": failures,
                    },
                )
            raise OpenWebRetrievalError(
                "search returned no results",
                context={"query": query.query, "failures": failures},
            )

        # Dedup by URL — keep first occurrence (highest-ranked provider)
        seen_urls: set[str] = set()
        deduped: list[SearchHit] = []
        for hit in combined_hits:
            if hit.url not in seen_urls:
                seen_urls.add(hit.url)
                deduped.append(hit)
        result = deduped[: query.top_k]
        logger.info(
            "SEARCH_RESULT query=%r hits=%d providers=%s",
            query.query,
            len(result),
            ",".join(providers),
        )
        return result

    async def retrieve(
        self,
        query: SearchQuery,
        *,
        fetch_request: FetchRequest | None = None,
        allow_partial: bool = False,
        trace_id: str | None = None,
        task: str | None = None,
    ) -> SourceRecordBatch:
        """Execute search + async fetch + extract for a deterministic output batch."""
        hits = await self.search(query, trace_id=trace_id, task=task)
        # Use provided fetch_request as a template for render_mode, user_agent, max_bytes.
        # Only those fields are used — the URL comes from each search hit.
        template = fetch_request
        records: list[SourceRecord] = []

        for hit in hits:
            per_hit_fetch = FetchRequest(
                url=hit.url,
                render_mode=template.render_mode if template else "auto",
                user_agent_profile=template.user_agent_profile if template else FetchRequest.model_fields["user_agent_profile"].default,
                max_bytes=template.max_bytes if template else 8_000_000,
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
                        ),
                    )
                else:
                    fetched = await self.fetcher.fetch(
                        per_hit_fetch, trace_id=trace_id, task=task,
                    )
                    extracted = self.fetcher.extract(
                        fetched, trace_id=trace_id, task=task,
                    )
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
                        ),
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
                    ),
                )

        return SourceRecordBatch(query=query, records=records)

    async def close(self) -> None:
        """Release resources held by the client and its async fetcher."""
        await self.fetcher.close()
        for adapter in self.adapters.adapters.values():
            if hasattr(adapter, "close"):
                adapter.close()
        if self._search_log is not None:
            self._search_log.close()

    async def __aenter__(self):
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context manager — release resources."""
        await self.close()
        return False
