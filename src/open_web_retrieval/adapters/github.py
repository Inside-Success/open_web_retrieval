"""GitHub repository search via the GitHub REST search API.

Added 2026-09-03: GitHub was only ever reached through generic web search
(Tavily/Exa) here -- a "whitelisted official provider" domain, not a
dedicated targeted probe -- unlike Reddit and Hacker News, which each got a
source-targeted probe because generic web search reaches them badly. Real
practitioner signal (what people are actually building, real repos solving
a problem) is exactly the kind of thing generic web search under-indexes
relative to a direct search against GitHub's own index.

Modeled directly on ``hackernews.py`` in this same directory -- same shape,
but requires an auth token (unauthenticated GitHub search is rate-limited to
10 requests/min, too low for reliable production use; authenticated is
30/min).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import TracebackType

import httpx

from open_web_retrieval.adapters.base import ProviderThrottle, SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery

_SEARCH_URL = "https://api.github.com/search/repositories"


class GitHubSearchAdapter(SearchAdapter):
    """Search GitHub repositories through the platform's own search index."""

    provider_name = "github"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float | None = 15.0,
        client: httpx.Client | None = None,
        request_throttle: ProviderThrottle | None = None,
    ) -> None:
        """Resolve the API token from env only when not explicitly provided."""

        self.api_key = os.environ.get("GITHUB_SEARCH_TOKEN", "") if api_key is None else api_key
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self._owns_client = client is None
        self._provider_throttle = request_throttle

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Search repositories. ``domains_allow``/``domains_deny`` unsupported."""

        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError(
                "GitHub does not support retrieval_instruction",
                context={"provider": self.provider_name},
            )
        if query.domains_allow or query.domains_deny:
            raise CapabilityNotSupportedError(
                "GitHub does not support domain filters",
                context={"provider": self.provider_name},
            )
        if not self.api_key:
            raise ProviderUnavailableError(
                "GitHub credentials incomplete: GITHUB_SEARCH_TOKEN not set",
                context={"provider": self.provider_name},
            )

        q = query.query.strip()
        if query.recency_days is not None:
            cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=query.recency_days)).date()
            q = f"{q} pushed:>{cutoff.isoformat()}"

        params = {"q": q, "per_page": str(query.top_k), "sort": "best-match"}
        try:
            with self.paced():
                response = self.client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "GitHub request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        if response.status_code == 401:
            raise ProviderUnavailableError(
                "GitHub rejected the API token (check GITHUB_SEARCH_TOKEN)",
                context={"provider": self.provider_name, "status": 401},
            )
        if response.status_code == 403:
            # GitHub returns 403 (not 429) for both auth-scope refusals and
            # secondary rate limits; the body distinguishes them, but both are
            # equally fatal to this call, so surface the message verbatim
            # rather than guess which one fired.
            raise RetrievalError(
                f"GitHub refused the search (403): {_error_message(response)}",
                context={"provider": self.provider_name, "status": 403},
            )
        if response.status_code != 200:
            raise RetrievalError(
                f"GitHub returned HTTP {response.status_code}",
                context={"provider": self.provider_name, "status": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError(
                "GitHub returned invalid JSON",
                context={"provider": self.provider_name},
            ) from exc

        raw_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            raise RetrievalError(
                "GitHub response did not contain an items list",
                context={"provider": self.provider_name, "query": query.query},
            )

        hits: list[SearchHit] = []
        for item in raw_items:
            if not isinstance(item, dict) or not item.get("html_url"):
                continue
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=item.get("full_name"),
                    url=str(item["html_url"]),
                    snippet=_optional_string(item.get("description")),
                    publisher="GitHub",
                    published_at=_parse_timestamp(item.get("pushed_at")),
                    rank=len(hits) + 1,
                    # Stars are unbounded and cannot share a relevance scale
                    # with providers that return normalized scores (same
                    # reasoning as Hacker News points).
                    score_hint=None,
                    language=None,
                    raw_payload={
                        "stargazers_count": item.get("stargazers_count"),
                        "forks_count": item.get("forks_count"),
                        "open_issues_count": item.get("open_issues_count"),
                        "language": item.get("language"),
                        "archived": item.get("archived"),
                        "topics": item.get("topics"),
                    },
                ),
            )
            if len(hits) >= query.top_k:
                break
        return hits

    def close(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            self.client.close()

    def __enter__(self) -> GitHubSearchAdapter:  # noqa: PYI034
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


def _parse_timestamp(value: object) -> datetime | None:
    """Parse a GitHub ISO timestamp into an aware UTC datetime."""

    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _error_message(response: httpx.Response) -> str:
    """Best-effort extraction of GitHub's error message, never raising itself."""

    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"]
    return response.text[:200]
