"""Reddit OAuth search with subreddit scoping and normalized provenance.

Source-ported with Brian's authorization from
``Inside-Success/open_web_retrieval@63848bc32b81e675ba86c6d54bf97b857bf5d279``.
Repository histories remain independent. Credentials are runtime-only.
"""

from __future__ import annotations

import os
import re
import time
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

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/search"
_DEFAULT_UA = "python:open-web-retrieval:0.11 (Reddit search adapter)"
_TOKEN_SKEW_SECONDS = 300


class RedditSearchAdapter(SearchAdapter):
    """Search Reddit posts using the OAuth script grant."""

    provider_name = "reddit"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        user_agent: str | None = None,
        timeout_seconds: float | None = 20.0,
        client: httpx.Client | None = None,
        request_throttle: ProviderThrottle | None = None,
    ) -> None:
        """Resolve only omitted credentials from env; explicit empty stays empty."""

        self.client_id = os.environ.get("REDDIT_CLIENT_ID", "") if client_id is None else client_id
        self.client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "") if client_secret is None else client_secret
        self.username = os.environ.get("REDDIT_USERNAME", "") if username is None else username
        self.password = os.environ.get("REDDIT_PASSWORD", "") if password is None else password
        self.user_agent = os.environ.get("REDDIT_USER_AGENT", _DEFAULT_UA) if user_agent is None else user_agent
        self._token: str | None = None
        self._token_expires_at = 0.0
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self._owns_client = client is None
        self._provider_throttle = request_throttle

    def _missing_credentials(self) -> list[str]:
        credentials = {
            "REDDIT_CLIENT_ID": self.client_id,
            "REDDIT_CLIENT_SECRET": self.client_secret,
            "REDDIT_USERNAME": self.username,
            "REDDIT_PASSWORD": self.password,
        }
        return [name for name, value in credentials.items() if not value]

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        missing = self._missing_credentials()
        if missing:
            raise ProviderUnavailableError(
                f"Reddit credentials incomplete: {', '.join(missing)} not set",
                context={"provider": self.provider_name},
            )
        try:
            with self.paced():
                response = self.client.post(
                    _TOKEN_URL,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "password", "username": self.username, "password": self.password},
                    headers={"User-Agent": self.user_agent},
                )
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError("Reddit token request failed", context={"provider": "reddit"}) from exc
        if response.status_code == 401:
            raise ProviderUnavailableError(
                "Reddit rejected the app credentials (check CLIENT_ID/CLIENT_SECRET)",
                context={"provider": "reddit", "status": 401},
            )
        if response.status_code != 200:
            raise RetrievalError(
                f"Reddit token endpoint returned HTTP {response.status_code}",
                context={"provider": "reddit", "status": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError("Reddit token endpoint returned invalid JSON", context={"provider": "reddit"}) from exc
        if not isinstance(payload, dict) or payload.get("error") or not payload.get("access_token"):
            error = payload.get("error", "") if isinstance(payload, dict) else ""
            raise ProviderUnavailableError(
                "Reddit rejected the account login (check USERNAME/PASSWORD; script grant cannot satisfy 2FA)",
                context={"provider": "reddit", "reddit_error": str(error)[:80]},
            )
        self._token = str(payload["access_token"])
        expires_in = float(payload.get("expires_in") or 3600)
        self._token_expires_at = time.monotonic() + max(60.0, expires_in - _TOKEN_SKEW_SECONDS)
        return self._token

    @staticmethod
    def _scoped_query(query: SearchQuery) -> str:
        value = query.query.strip()
        subreddits = [
            re.sub(r"^/?r/", "", str(item).strip(), flags=re.IGNORECASE).lower()
            for item in query.domains_allow
        ]
        subreddits = [item for item in subreddits if item]
        if not subreddits:
            return value
        scope = " OR ".join(f"subreddit:{item}" for item in dict.fromkeys(subreddits))
        return f"({value}) ({scope})"

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Search posts; ``domains_allow`` is interpreted as subreddit scope."""

        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError("Reddit does not support retrieval_instruction", context={"provider": "reddit"})
        if query.domains_deny:
            raise CapabilityNotSupportedError("Reddit does not support domain exclusion", context={"provider": "reddit"})
        token = self._access_token()
        params = {"q": self._scoped_query(query), "limit": str(min(query.top_k, 100)), "sort": "relevance", "type": "link"}
        if query.recency_days is not None:
            days = query.recency_days
            params["t"] = "day" if days <= 1 else "week" if days <= 7 else "month" if days <= 31 else "year" if days <= 366 else "all"
        try:
            with self.paced():
                response = self.client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={"Authorization": f"bearer {token}", "User-Agent": self.user_agent},
                )
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError("Reddit request failed", context={"provider": "reddit", "query": query.query}) from exc
        if response.status_code == 401:
            self._token = None
            raise RetrievalError("Reddit rejected the access token (it has been invalidated)", context={"provider": "reddit"})
        if response.status_code != 200:
            raise RetrievalError(
                f"Reddit returned HTTP {response.status_code}",
                context={"provider": "reddit", "ratelimit_remaining": response.headers.get("x-ratelimit-remaining")},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError("Reddit returned invalid JSON", context={"provider": "reddit"}) from exc
        children = ((payload.get("data") or {}).get("children") or []) if isinstance(payload, dict) else []
        cutoff = time.time() - query.recency_days * 86400 if query.recency_days else None
        hits: list[SearchHit] = []
        for child in children:
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict) or not data.get("permalink"):
                continue
            created = data.get("created_utc")
            if cutoff is not None and isinstance(created, (int, float)) and created < cutoff:
                continue
            published = datetime.fromtimestamp(float(created), tz=timezone.utc) if isinstance(created, (int, float)) else None
            body_value = data.get("selftext")
            body = body_value if isinstance(body_value, str) else ""
            subreddit_value = data.get("subreddit")
            subreddit = subreddit_value if isinstance(subreddit_value, str) else ""
            raw = {
                "subreddit": subreddit,
                "author": data.get("author"),
                "score": data.get("score"),
                "upvote_ratio": data.get("upvote_ratio"),
                "num_comments": data.get("num_comments"),
                "created_utc": created,
                "over_18": data.get("over_18"),
                "link_flair_text": data.get("link_flair_text"),
                "external_url": data.get("url") if data.get("url") != data.get("permalink") else None,
            }
            if len(body) > 100:
                raw["raw_content"] = body
            hits.append(SearchHit(
                provider="reddit", query=query.query, title=data.get("title"),
                url=f"https://reddit.com{data['permalink']}", snippet=body[:400] or None,
                publisher=f"r/{subreddit}" if subreddit else "Reddit", published_at=published,
                rank=len(hits) + 1, score_hint=None, raw_payload=raw,
            ))
            if len(hits) >= query.top_k:
                break
        return hits

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> RedditSearchAdapter:  # noqa: PYI034
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        self.close()
