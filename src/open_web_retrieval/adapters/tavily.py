"""Tavily search adapter."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery


def _normalize_host(url: str) -> str | None:
    """Extract a stable publisher hint from a result URL."""
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return None
    return netloc or None


class TavilySearchAdapter(SearchAdapter):
    """Adapter for Tavily's hosted search API."""

    provider_name = "tavily"

    def _resolve_search_depth(self, query: SearchQuery) -> str:
        """Resolve Tavily search depth from the shared query contract."""
        if query.search_depth is not None:
            resolved = query.search_depth
        elif query.result_detail == "summary":
            resolved = "basic"
        elif query.result_detail == "chunks":
            resolved = "advanced"
        else:
            resolved = "advanced"
        if resolved == "advanced" and query.result_detail == "summary":
            raise CapabilityNotSupportedError(
                "Tavily cannot provide summary-only detail with advanced depth",
                context={"provider": self.provider_name, "query": query.query},
            )
        return resolved

    def _resolve_topic(self, query: SearchQuery) -> str | None:
        """Resolve Tavily topic hints from the shared corpus field."""
        if query.corpus is None or query.corpus == "general":
            return None
        if query.corpus == "news":
            return "news"
        raise CapabilityNotSupportedError(
            f"Tavily does not support corpus={query.corpus!r}",
            context={"provider": self.provider_name, "query": query.query},
        )

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float | None = None,
        base_url: str = "https://api.tavily.com/search",
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize Tavily transport configuration."""
        if not api_key:
            raise ProviderUnavailableError(
                "Tavily provider requires api_key",
                context={"provider": self.provider_name},
            )
        self.api_key = api_key
        self.base_url = base_url
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute Tavily search and return normalized results."""
        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError(
                "Tavily does not support retrieval_instruction",
                context={"provider": self.provider_name, "query": query.query},
            )
        search_depth = self._resolve_search_depth(query)
        body: dict[str, object] = {
            "api_key": self.api_key,
            "query": query.query,
            "max_results": query.top_k,
            "search_depth": search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        if search_depth == "advanced" and query.result_detail == "chunks":
            body["chunks_per_source"] = query.detail_budget or 3
        if query.domains_allow:
            body["include_domains"] = list(query.domains_allow)
        if query.domains_deny:
            body["exclude_domains"] = list(query.domains_deny)
        if query.recency_days is not None:
            body["days"] = query.recency_days
        topic = self._resolve_topic(query)
        if topic is not None:
            body["topic"] = topic

        try:
            response = self.client.post(self.base_url, json=body)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "Tavily request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise RetrievalError(
                    "Tavily API key is invalid, missing, or unauthorized",
                    context={
                        "provider": self.provider_name,
                        "query": query.query,
                        "status_code": status_code,
                    },
                ) from exc
            if status_code == 429:
                retry_after = exc.response.headers.get("Retry-After", "unknown")
                raise RetrievalError(
                    f"Tavily API rate limited (Retry-After: {retry_after})",
                    context={
                        "provider": self.provider_name,
                        "query": query.query,
                        "status_code": 429,
                        "retry_after": retry_after,
                    },
                ) from exc
            raise RetrievalError(
                f"Tavily request failed (HTTP {status_code})",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_code": status_code,
                    "status_message": str(exc),
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise RetrievalError(
                "Tavily request failed",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_message": str(exc),
                },
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError(
                "Tavily response is not JSON",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise RetrievalError(
                "Tavily payload missing expected result list",
                context={"provider": self.provider_name, "query": query.query},
            )

        hits: list[SearchHit] = []
        for idx, result in enumerate(raw_results[: query.top_k], start=1):
            if not isinstance(result, dict):
                continue
            url = result.get("url", "")
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=result.get("title"),
                    url=url,
                    snippet=result.get("content"),
                    publisher=_normalize_host(url),
                    published_at=None,
                    rank=idx,
                    score_hint=result.get("score"),
                    language=None,
                    raw_payload=dict(result),
                )
            )
        return hits

    def close(self) -> None:
        """Close owned HTTP client to release sockets."""
        if getattr(self, "_owns_client", False):
            self.client.close()

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and release resources."""
        self.close()
        return False

    def __del__(self) -> None:
        """Close owned client at object deletion as a fallback."""
        self.close()
