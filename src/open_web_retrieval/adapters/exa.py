"""Exa search adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import OpenWebRetrievalError, ProviderUnavailableError, RetrievalError
from open_web_retrieval.models import SearchHit, SearchQuery


def _normalize_host(url: str) -> str | None:
    """Extract a stable publisher hint from a result URL."""
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return None
    return netloc or None


def _parse_published(value: str | None) -> datetime | None:
    """Parse Exa published-date strings when present."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_start_iso(recency_days: int | None) -> str | None:
    """Convert recency-days into Exa's startPublishedDate ISO string."""
    if recency_days is None:
        return None
    return (datetime.now(UTC) - timedelta(days=recency_days)).isoformat().replace("+00:00", "Z")


def _snippet_from_result(result: dict[str, object]) -> str | None:
    """Choose the best available Exa text preview for the normalized snippet."""
    highlights = result.get("highlights")
    if isinstance(highlights, list) and highlights:
        first = highlights[0]
        if isinstance(first, str):
            return first
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text[:1200]
    return None


class ExaSearchAdapter(SearchAdapter):
    """Adapter for Exa's hosted search API."""

    provider_name = "exa"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float | None = None,
        base_url: str = "https://api.exa.ai/search",
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize Exa transport configuration."""
        if not api_key:
            raise ProviderUnavailableError(
                "Exa provider requires api_key",
                context={"provider": self.provider_name},
            )
        self.api_key = api_key
        self.base_url = base_url
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute Exa search and return normalized results."""
        body: dict[str, object] = {
            "query": query.query,
            "type": "deep",
            "numResults": query.top_k,
            "contents": {
                "highlights": {
                    "query": query.query,
                    "maxCharacters": 1200,
                },
            },
        }
        if query.domains_allow:
            body["includeDomains"] = list(query.domains_allow)
        if query.domains_deny:
            body["excludeDomains"] = list(query.domains_deny)
        start_published_date = _recency_start_iso(query.recency_days)
        if start_published_date is not None:
            body["startPublishedDate"] = start_published_date

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            response = self.client.post(self.base_url, headers=headers, json=body)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "Exa request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise RetrievalError(
                    "Exa API key is invalid, missing, or unauthorized",
                    context={
                        "provider": self.provider_name,
                        "query": query.query,
                        "status_code": status_code,
                    },
                ) from exc
            if status_code == 429:
                retry_after = exc.response.headers.get("Retry-After", "unknown")
                raise RetrievalError(
                    f"Exa API rate limited (Retry-After: {retry_after})",
                    context={
                        "provider": self.provider_name,
                        "query": query.query,
                        "status_code": 429,
                        "retry_after": retry_after,
                    },
                ) from exc
            raise RetrievalError(
                f"Exa request failed (HTTP {status_code})",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_code": status_code,
                    "status_message": str(exc),
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise RetrievalError(
                "Exa request failed",
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
                "Exa response is not JSON",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise RetrievalError(
                "Exa payload missing expected result list",
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
                    snippet=_snippet_from_result(result),
                    publisher=_normalize_host(url),
                    published_at=_parse_published(result.get("publishedDate") if isinstance(result.get("publishedDate"), str) else None),
                    rank=idx,
                    score_hint=None,
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
