"""Reddit search adapter (OAuth script grant, practitioner-venue targeted).

WHY THIS EXISTS. Reddit is the highest-value practitioner venue for applied
engineering questions, and it is precisely where open-web retrieval fails
hardest: on a live grounded-research run (2026-07-27) SIX Reddit URLs needed the
``provider raw_content`` fetch fallback because Reddit blocks generic page
fetches. Web-search-then-fetch keeps arriving at Reddit's front door and being
turned away. Querying Reddit's OWN search index sidesteps that entirely, and
returns first-hand reports by construction rather than by SEO luck.

Deliberately NOT asyncpraw. ``SearchAdapter.search`` is synchronous and asyncpraw
is async, so using it would mean either a sync/async bridge or a contract change
- and Reddit's plain OAuth search endpoint already returns everything a
``SearchHit`` needs. One fewer dependency, no bridge.

CREDENTIALS (script grant, all four required):
    REDDIT_CLIENT_ID      the app's id
    REDDIT_CLIENT_SECRET  the app's secret
    REDDIT_USERNAME       the account the app acts as
    REDDIT_PASSWORD       that account's password

Note this is an account LOGIN, not a scoped key: whatever this adapter does is
attributable to that account, and a rate-limit strike lands on it. Use a
dedicated bot account, never a person's own.

RATE DISCIPLINE: measured 2026-07-28 against the live API - Reddit returned
``x-ratelimit-remaining: 998`` of 1000 with a 546s reset, i.e. ~1000 requests
per 10 minutes. The base-class throttle paces this provider at 100/min with
concurrency 2, comfortably inside that. Reddit also BLOCKS generic user agents,
so a descriptive UA is an API requirement rather than politeness.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/search"
_DEFAULT_UA = "python:open-web-retrieval:0.1 (Inside Success research)"
# Refresh this far before the token's stated expiry so a long run never dies
# mid-flight on an expiring credential.
_TOKEN_SKEW_SECONDS = 300


class RedditSearchAdapter(SearchAdapter):
    """Adapter for Reddit's OAuth search API."""

    provider_name = "reddit"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        user_agent: str | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        """Credentials fall back to the environment when not passed explicitly."""
        self.client_id = (
            os.environ.get("REDDIT_CLIENT_ID", "") if client_id is None else client_id
        )
        self.client_secret = (
            os.environ.get("REDDIT_CLIENT_SECRET", "")
            if client_secret is None
            else client_secret
        )
        self.username = (
            os.environ.get("REDDIT_USERNAME", "") if username is None else username
        )
        self.password = (
            os.environ.get("REDDIT_PASSWORD", "") if password is None else password
        )
        self.user_agent = (
            os.environ.get("REDDIT_USER_AGENT", _DEFAULT_UA)
            if user_agent is None
            else user_agent
        )
        self._token: str | None = None
        self._token_expires_at = 0.0
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)
            self._owns_client = True

    # -- auth ---------------------------------------------------------------

    def _missing_credentials(self) -> list[str]:
        pairs = {
            "REDDIT_CLIENT_ID": self.client_id,
            "REDDIT_CLIENT_SECRET": self.client_secret,
            "REDDIT_USERNAME": self.username,
            "REDDIT_PASSWORD": self.password,
        }
        return [name for name, value in pairs.items() if not value]

    def _access_token(self) -> str:
        """Cached bearer token; minted on demand, reused until near expiry.

        The script grant returns a token good for ~24h, so this is one request
        per process rather than one per search.
        """
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
                    data={
                        "grant_type": "password",
                        "username": self.username,
                        "password": self.password,
                    },
                    headers={"User-Agent": self.user_agent},
                )
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "Reddit token request failed",
                context={"provider": self.provider_name},
            ) from exc

        # 401 vs a 200-with-error body distinguish APP credentials from USER
        # credentials. Reporting them identically sends an operator to re-paste
        # the wrong secret - verified against the live API 2026-07-28.
        if response.status_code == 401:
            raise ProviderUnavailableError(
                "Reddit rejected the app credentials (check CLIENT_ID/CLIENT_SECRET)",
                context={"provider": self.provider_name, "status": 401},
            )
        if response.status_code != 200:
            raise RetrievalError(
                f"Reddit token endpoint returned HTTP {response.status_code}",
                context={"provider": self.provider_name, "status": response.status_code},
            )

        payload = response.json()
        if payload.get("error") or not payload.get("access_token"):
            raise ProviderUnavailableError(
                "Reddit rejected the account login (check USERNAME/PASSWORD; the "
                "script grant cannot satisfy 2FA)",
                context={"provider": self.provider_name,
                         "reddit_error": str(payload.get("error", ""))[:80]},
            )

        self._token = payload["access_token"]
        expires_in = float(payload.get("expires_in") or 3600)
        self._token_expires_at = time.monotonic() + max(60.0, expires_in - _TOKEN_SKEW_SECONDS)
        return self._token

    # -- query shaping ------------------------------------------------------

    @staticmethod
    def _scoped_query(query: SearchQuery) -> str:
        """Build the ``q`` value, scoping to subreddits when the caller asks.

        ``domains_allow`` carries SUBREDDIT names for this provider — Reddit has
        one host, so a domain filter is meaningless here and the field's only
        sensible reading is venue scoping (this adapter used to raise with the
        message "use subreddit scoping"). Names are accepted bare (``devops``)
        or prefixed (``r/devops``, ``/r/devops``).

        Measured against the live API on 2026-07-29, 12 hits per shape:

            long sentence                        ->  0 hits
            short keywords                       -> 12 hits,  5 on-topic
            short keywords + subreddit: filter   -> 12 hits, 12 on-topic
            long sentence + subreddit: filter    ->  0 hits

        So the filter earns perfect precision, but ONLY over a keyword-shaped
        query — Reddit's index returns nothing at all for a natural-language
        sentence, with or without scoping. Callers must send keywords.
        """
        q = (query.query or "").strip()
        subs = [
            re.sub(r"^/?r/", "", str(s).strip(), flags=re.IGNORECASE).lower()
            for s in (query.domains_allow or ())
        ]
        subs = [s for s in subs if s]
        if not subs:
            return q
        scope = " OR ".join(f"subreddit:{s}" for s in dict.fromkeys(subs))
        return f"({q}) ({scope})" if q else f"({scope})"

    # -- search -------------------------------------------------------------

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute a Reddit search; returns normalized post records."""
        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError(
                "Reddit does not support retrieval_instruction",
                context={"provider": self.provider_name, "query": query.query},
            )
        if query.domains_deny:
            raise CapabilityNotSupportedError(
                "Reddit does not support domain exclusion",
                context={"provider": self.provider_name, "query": query.query},
            )

        token = self._access_token()
        params: dict[str, str] = {
            "q": self._scoped_query(query),
            "limit": str(min(max(query.top_k, 1), 100)),
            "sort": "relevance",
            "type": "link",  # posts, not subreddits or users
        }
        # Reddit's own coarse recency buckets; the exact day cutoff is applied
        # client-side below because 't' has no finer granularity than these.
        if query.recency_days is not None:
            days = int(query.recency_days)
            params["t"] = (
                "day" if days <= 1 else "week" if days <= 7
                else "month" if days <= 31 else "year" if days <= 366 else "all"
            )

        try:
            with self.paced():
                response = self.client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={
                        "Authorization": f"bearer {token}",
                        "User-Agent": self.user_agent,
                    },
                )
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "Reddit request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "Reddit request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        if response.status_code == 401:
            # The cached token went stale early (revoked app, password change).
            # Drop it so the next call re-mints rather than looping on a dead one.
            self._token = None
            raise RetrievalError(
                "Reddit rejected the access token (it has been invalidated)",
                context={"provider": self.provider_name, "query": query.query},
            )
        if response.status_code != 200:
            raise RetrievalError(
                f"Reddit returned HTTP {response.status_code}",
                context={"provider": self.provider_name, "query": query.query,
                         "ratelimit_remaining": response.headers.get("x-ratelimit-remaining")},
            )

        children = ((response.json().get("data") or {}).get("children") or [])
        cutoff_ts = None
        if query.recency_days is not None:
            cutoff_ts = time.time() - int(query.recency_days) * 86400

        hits: list[SearchHit] = []
        rank = 0
        for child in children:
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict):
                continue
            permalink = data.get("permalink")
            if not permalink:
                continue  # no permalink means no citable URL
            created = data.get("created_utc")
            if cutoff_ts is not None and isinstance(created, (int, float)) and created < cutoff_ts:
                continue

            published_at = None
            if isinstance(created, (int, float)):
                published_at = datetime.fromtimestamp(float(created), tz=timezone.utc)

            selftext = data.get("selftext") or ""
            subreddit = data.get("subreddit") or ""
            payload = {
                "subreddit": subreddit,
                "author": data.get("author"),
                "score": data.get("score"),
                "upvote_ratio": data.get("upvote_ratio"),
                "num_comments": data.get("num_comments"),
                "created_utc": created,
                "over_18": data.get("over_18"),
                "link_flair_text": data.get("link_flair_text"),
                # The submitted link, kept distinct from the discussion we cite.
                "external_url": data.get("url") if data.get("url") != permalink else None,
            }
            if len(selftext) > 100:
                payload["raw_content"] = selftext

            rank += 1
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=data.get("title"),
                    url=f"https://reddit.com{permalink}",
                    snippet=selftext[:400] if selftext else None,
                    publisher=f"r/{subreddit}" if subreddit else "Reddit",
                    published_at=published_at,
                    rank=rank,
                    # Upvotes are UNBOUNDED and vote-fuzzed by Reddit, so they
                    # are not comparable to Tavily's 0-1 score_hint. Same
                    # discipline as the OpenAlex and Hacker News adapters: leave
                    # score_hint None, let the raw score ride the payload.
                    score_hint=None,
                    language=None,
                    raw_payload=payload,
                )
            )
            if len(hits) >= query.top_k:
                break
        return hits

    def close(self) -> None:
        """Close owned HTTP client to release sockets."""
        if getattr(self, "_owns_client", False):
            self.client.close()

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, *exc_info):
        """Exit context manager, closing owned resources."""
        self.close()
