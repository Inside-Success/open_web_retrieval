"""SearxNG search adapter."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import OpenWebRetrievalError, RetrievalError
from open_web_retrieval.models import SearchHit, SearchQuery


def _normalize_host(url: str) -> str | None:
    """Extract a stable publisher hint from a URL."""
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return None
    return netloc or None


def _parse_published(value: str | None) -> datetime | None:
    """Attempt to parse optional datetime-like fields from SearxNG results."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SearxNGSearchAdapter(SearchAdapter):
    """Adapter for local SearxNG deployments."""

    provider_name = "searxng"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8080",
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize SearxNG transport endpoint."""
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute SearxNG search and return normalized results."""
        endpoint = f"{self.base_url}/search"
        params = {
            "q": query.query,
            "format": "json",
            "language": query.locale or "en",
            "categories": "general",
        }
        try:
            response = self.client.get(endpoint, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "SearxNG request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"SearxNG request failed (HTTP {exc.response.status_code})",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_code": exc.response.status_code,
                    "status_message": str(exc),
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise RetrievalError(
                "SearxNG request failed",
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
                "SearxNG response is not JSON",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise RetrievalError(
                "SearxNG payload missing expected result list",
                context={"provider": self.provider_name, "query": query.query},
            )

        hits: list[SearchHit] = []
        for idx, result in enumerate(raw_results[: query.top_k], start=1):
            if not isinstance(result, dict):
                continue
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=result.get("title"),
                    url=result.get("url", ""),
                    snippet=result.get("content"),
                    publisher=_normalize_host(result.get("url", "")),
                    published_at=_parse_published(result.get("published")),
                    rank=idx,
                    score_hint=result.get("score"),
                    language=result.get("language"),
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
        """Exit context manager — release resources."""
        self.close()
        return False

    def __del__(self) -> None:
        """Close owned HTTP client at object deletion (fallback)."""
        self.close()
