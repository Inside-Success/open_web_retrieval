"""Hacker News search adapter (keyless, practitioner-venue targeted).

WHY THIS EXISTS. Open-web search asks a general index to surface practitioner
evidence and hopes SEO cooperates. Measured on a live grounded-research run
(2026-07-27): 44 of 50 collected sources had provenance the source classifier
could not vouch for, and per-citation faithfulness came in at 0.767 against a
0.80 gate. Source-TARGETED retrieval inverts that — HN's own index contains HN
and nothing else, so practitioner discussion is returned by construction rather
than by luck.

Keyless: the HN Algolia API (https://hn.algolia.com/api) requires no auth, no
account, and no billing. Adapted from the equivalent client in
Inside-Success/social-research-mcp (Brian Mills) — reshaped to this package's
SearchAdapter contract, given recency support, and given the score_hint
discipline described below.

WHAT THE URL POINTS AT: the HN discussion thread, not the submitted article.
The thread IS the practitioner evidence for our purposes; the submitted link
rides ``raw_payload["external_url"]`` for a consumer that wants the artifact
instead. ``raw_payload["raw_content"]`` carries the submission text when the
post has any, so a blocked fetch still leaves verifiable text behind.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery

# https, not the http:// the upstream client used — this carries no secrets but
# there is no reason to speak plaintext to a public API.
_BASE_URL = "https://hn.algolia.com/api/v1/search"
_ITEM_URL = "https://news.ycombinator.com/item?id={item_id}"


class HackerNewsSearchAdapter(SearchAdapter):
    """Adapter for the keyless Hacker News (Algolia) search API."""

    provider_name = "hackernews"

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        """Keyless: there is nothing to configure but the HTTP client."""
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)
            self._owns_client = True

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute an HN story search; returns normalized discussion threads."""
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
            # Stories only. Comments match too, but a bare comment has no title
            # and no stable standalone URL — the thread is the citable unit, and
            # its comments come back when a consumer fetches it.
            "tags": "story",
            "hitsPerPage": str(min(max(query.top_k, 1), 50)),
        }
        if query.recency_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(query.recency_days))
            params["numericFilters"] = f"created_at_i>{int(cutoff.timestamp())}"

        try:
            with self.paced():
                response = self.client.get(_BASE_URL, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "Hacker News request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"Hacker News returned HTTP {exc.response.status_code}",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "Hacker News request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_hits = response.json().get("hits", [])
        hits: list[SearchHit] = []
        rank = 0
        for result in raw_hits:
            if not isinstance(result, dict):
                continue
            item_id = result.get("objectID")
            if not item_id:
                continue  # no id means no citable thread URL
            story_text = result.get("story_text") or result.get("comment_text") or ""
            published_at = None
            created = result.get("created_at")
            if isinstance(created, str) and created:
                try:
                    published_at = datetime.fromisoformat(
                        created.replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    pass

            payload = dict(result)
            # The submitted link, kept distinct from the thread we cite.
            external = result.get("url")
            if isinstance(external, str) and external.startswith("http"):
                payload["external_url"] = external
            if len(story_text) > 100:
                payload["raw_content"] = story_text

            rank += 1
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=result.get("title") or result.get("story_title"),
                    url=_ITEM_URL.format(item_id=item_id),
                    snippet=story_text[:400] if story_text else None,
                    publisher="Hacker News",
                    published_at=published_at,
                    rank=rank,
                    # points is UNBOUNDED (a front-page post clears 2000) and so
                    # is never comparable to Tavily's 0-1 score_hint. Same
                    # landmine the OpenAlex adapter documents: leave score_hint
                    # None and let the raw value ride the payload, rather than
                    # inventing a scale two providers cannot share.
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
