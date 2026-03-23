"""Brave search adapter."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import OpenWebRetrievalError, ProviderUnavailableError, RetrievalError
from open_web_retrieval.models import SearchHit, SearchQuery


def _parse_published(value: str | None) -> datetime | None:
    """Parse Brave timestamp strings into UTC datetimes when possible."""
    if not value:
        return None
    stripped = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(stripped)
    except ValueError:
        return None


class BraveSearchAdapter(SearchAdapter):
    """Adapter for Brave Web Search API v1 endpoint."""

    provider_name = "brave"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float | None = None,
        base_url: str = "https://api.search.brave.com/res/v1/web/search",
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize Brave API integration metadata."""
        if not api_key:
            raise ProviderUnavailableError(
                "Brave provider requires api_key",
                context={"provider": self.provider_name},
            )
        self.api_key = api_key
        self.base_url = base_url
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute Brave search and return normalized results."""
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        params = {
            "q": query.query,
            "count": min(query.top_k, 20),
            "search_lang": query.locale or "en",
        }
        if query.recency_days is not None:
            params["freshness"] = f"pd{query.recency_days}"

        try:
            response = self.client.get(self.base_url, headers=headers, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "Brave request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPError as exc:
            status_code = None
            if exc.response is not None and hasattr(exc.response, "status_code"):
                status_code = exc.response.status_code
            raise RetrievalError(
                "Brave request failed",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_code": status_code,
                    "status_message": str(exc),
                },
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError(
                "Brave response is not JSON",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_results = payload.get("web", {}).get("results", [])
        if not isinstance(raw_results, list):
            raise RetrievalError(
                "Brave response payload missing expected result list",
                context={"provider": self.provider_name, "query": query.query},
            )

        hits: list[SearchHit] = []
        for idx, result in enumerate(raw_results[: query.top_k], start=1):
            if not isinstance(result, Mapping):
                continue
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=result.get("title"),
                    url=result.get("url", ""),
                    snippet=result.get("description"),
                    publisher=result.get("profile", {}).get("name"),
                    published_at=_parse_published(result.get("age")),
                    rank=idx,
                    score_hint=None,
                    language=result.get("lang"),
                    raw_payload=dict(result),
                )
            )
        return hits

    def __del__(self) -> None:
        """Close owned HTTP client to avoid leaked sockets."""
        if self._owns_client:
            self.client.close()
