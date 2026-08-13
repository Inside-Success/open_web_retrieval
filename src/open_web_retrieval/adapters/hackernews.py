"""Keyless, source-targeted Hacker News search adapter.

Source-ported from ``Inside-Success/open_web_retrieval`` at
``98e54bfed2c0366ce8c8e64a59d80de41e8aa917`` with contract and testability
adaptations for the canonical upstream.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any

import httpx

from open_web_retrieval.adapters.base import ProviderThrottle, SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery

_BASE_URL = "https://hn.algolia.com/api/v1/search"
_ITEM_URL = "https://news.ycombinator.com/item?id={item_id}"


class HackerNewsSearchAdapter(SearchAdapter):
    """Search Hacker News stories through its public Algolia index."""

    provider_name = "hackernews"

    def __init__(
        self,
        *,
        timeout_seconds: float | None = 15.0,
        client: httpx.Client | None = None,
        request_throttle: ProviderThrottle | None = None,
    ) -> None:
        """Configure the keyless HTTP transport and optional test throttle."""

        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._provider_throttle = request_throttle

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Return normalized HN discussion threads for a search query."""

        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError(
                "Hacker News does not support retrieval_instruction",
                context={"provider": self.provider_name, "query": query.query},
            )
        if query.domains_allow or query.domains_deny:
            raise CapabilityNotSupportedError(
                "Hacker News does not support domain filters",
                context={"provider": self.provider_name, "query": query.query},
            )

        params: dict[str, str] = {
            "query": query.query,
            "tags": "story",
            "hitsPerPage": str(query.top_k),
        }
        if query.recency_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=query.recency_days)
            params["numericFilters"] = f"created_at_i>{int(cutoff.timestamp())}"

        try:
            with self.paced():
                response = self.client.get(_BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "Hacker News request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"Hacker News returned HTTP {exc.response.status_code}",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_code": exc.response.status_code,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "Hacker News request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except ValueError as exc:
            raise RetrievalError(
                "Hacker News returned invalid JSON",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_hits = payload.get("hits") if isinstance(payload, dict) else None
        if not isinstance(raw_hits, list):
            raise RetrievalError(
                "Hacker News response did not contain a hits list",
                context={"provider": self.provider_name, "query": query.query},
            )

        hits: list[SearchHit] = []
        for result in raw_hits:
            if not isinstance(result, dict):
                continue
            item_id = result.get("objectID")
            if not item_id:
                continue

            story_text = result.get("story_text") or result.get("comment_text") or ""
            if not isinstance(story_text, str):
                story_text = ""
            published_at = _parse_published_at(result.get("created_at"))
            normalized_payload: dict[str, Any] = dict(result)
            external_url = result.get("url")
            if isinstance(external_url, str) and external_url.startswith("http"):
                normalized_payload["external_url"] = external_url
            if len(story_text) > 100:
                normalized_payload["raw_content"] = story_text

            hits.append(
                SearchHit(
                    provider="hackernews",
                    query=query.query,
                    title=_optional_string(result.get("title") or result.get("story_title")),
                    url=_ITEM_URL.format(item_id=item_id),
                    snippet=story_text[:400] or None,
                    publisher="Hacker News",
                    published_at=published_at,
                    rank=len(hits) + 1,
                    # HN points are unbounded and cannot share a relevance scale
                    # with providers that return normalized scores.
                    score_hint=None,
                    language=None,
                    raw_payload=normalized_payload,
                ),
            )
            if len(hits) >= query.top_k:
                break
        return hits

    def close(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            self.client.close()

    # ``typing.Self`` is unavailable on the package's Python 3.10 floor.
    def __enter__(self) -> HackerNewsSearchAdapter:  # noqa: PYI034
        """Enter a context that owns this adapter's transport."""

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close owned resources when leaving a context."""

        self.close()


def _optional_string(value: object) -> str | None:
    """Return a non-empty string or ``None`` for provider-owned values."""

    return value if isinstance(value, str) and value else None


def _parse_published_at(value: object) -> datetime | None:
    """Parse an HN ISO timestamp into an aware UTC datetime."""

    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc,
        )
    except ValueError:
        return None
