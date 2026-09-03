"""X (Twitter) search via the twitterapi.io direct provider.

Added 2026-09-03: X/Twitter had zero coverage from any existing adapter here
(brave/searxng/tavily/exa all reach it badly or not at all -- 0 of 439 real
citations across 13 archived Inside-Success/grounded-research production runs;
see that repo's investigation writeup, Brian's personal
BrianMills2718/investigations repo, 2026-09-03-grounded-research-source-coverage-finding.md).
Modeled directly on ``reddit.py`` in this same directory -- single-key auth
instead of Reddit's OAuth token exchange, otherwise the same shape.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
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

_SEARCH_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"


class XSearchAdapter(SearchAdapter):
    """Search X/Twitter posts using the twitterapi.io direct provider.

    twitterapi.io is a pay-as-you-go direct reseller, not X's own developer
    API -- no documented uptime SLA. Cost: $0.15/1k tweets (no markup). A
    RapidAPI-backed fallback backend exists in Brian's personal
    ``mcp-servers/social-media`` server for outage/reliability contingency;
    this adapter deliberately supports only the primary backend to keep the
    contract small, matching this repo's "avoid speculative abstractions"
    principle -- add a fallback here only if a real reliability problem is
    observed, not preemptively.
    """

    provider_name = "x"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float | None = 20.0,
        client: httpx.Client | None = None,
        request_throttle: ProviderThrottle | None = None,
    ) -> None:
        """Resolve the API key from env only when not explicitly provided."""

        self.api_key = os.environ.get("TWITTERAPI_IO_API_KEY", "") if api_key is None else api_key
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self._owns_client = client is None
        self._provider_throttle = request_throttle

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Search recent posts. ``domains_allow``/``domains_deny`` unsupported."""

        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError("X does not support retrieval_instruction", context={"provider": "x"})
        if query.domains_allow or query.domains_deny:
            raise CapabilityNotSupportedError("X does not support domain scoping", context={"provider": "x"})
        if not self.api_key:
            raise ProviderUnavailableError(
                "X credentials incomplete: TWITTERAPI_IO_API_KEY not set",
                context={"provider": self.provider_name},
            )
        q = query.query.strip()
        if query.recency_days is not None:
            # twitterapi.io advanced search accepts operator syntax in the
            # query string itself (no separate recency param, unlike Reddit's
            # `t=`); `since:` needs a date, so compute it from recency_days.
            since = datetime.now(tz=timezone.utc).date().isoformat()
            q = f"{q} since:{since}"
        params = {"query": q, "queryType": "Latest"}
        try:
            with self.paced():
                response = self.client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={"X-API-Key": self.api_key},
                )
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError("X request failed", context={"provider": "x", "query": query.query}) from exc
        if response.status_code == 401:
            raise ProviderUnavailableError(
                "X rejected the API key (check TWITTERAPI_IO_API_KEY)",
                context={"provider": "x", "status": 401},
            )
        if response.status_code != 200:
            raise RetrievalError(
                f"X returned HTTP {response.status_code}",
                context={"provider": "x", "status": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError("X returned invalid JSON", context={"provider": "x"}) from exc
        tweets = payload.get("tweets") if isinstance(payload, dict) else None
        tweets = tweets if isinstance(tweets, list) else []
        hits: list[SearchHit] = []
        for tweet in tweets:
            if not isinstance(tweet, dict) or not tweet.get("url"):
                continue
            created_raw = tweet.get("createdAt")
            published = None
            if isinstance(created_raw, str) and created_raw:
                try:
                    # twitterapi.io format: "Thu Sep 03 11:34:12 +0000 2026"
                    published = datetime.strptime(created_raw, "%a %b %d %H:%M:%S %z %Y")
                except ValueError:
                    published = None
            author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
            raw = {
                "author": author.get("userName"),
                "author_followers": author.get("followers"),
                "author_verified": author.get("isVerified") or author.get("isBlueVerified"),
                "like_count": tweet.get("likeCount"),
                "retweet_count": tweet.get("retweetCount"),
                "reply_count": tweet.get("replyCount"),
                "view_count": tweet.get("viewCount"),
            }
            hits.append(SearchHit(
                provider="x", query=query.query, title=tweet.get("text"),
                url=str(tweet["url"]), snippet=(tweet.get("text") or "")[:400] or None,
                publisher=f"@{author.get('userName')}" if author.get("userName") else "X",
                published_at=published, rank=len(hits) + 1,
                score_hint=float(tweet["likeCount"]) if isinstance(tweet.get("likeCount"), (int, float)) else None,
                raw_payload=raw,
            ))
            if len(hits) >= query.top_k:
                break
        return hits

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> XSearchAdapter:  # noqa: PYI034
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        self.close()
