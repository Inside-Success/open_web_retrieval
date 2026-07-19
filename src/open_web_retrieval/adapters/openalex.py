"""OpenAlex scholarly search adapter (keyless, open-access-gated).

OpenAlex (https://openalex.org) indexes scholarly works with no API key
required. This adapter is deliberately OA-GATED: it returns only works whose
full text is actually reachable (an open-access PDF or landing page), so a
consumer never mints a citation it cannot later fetch and verify. The
reconstructed abstract rides ``raw_payload["raw_content"]`` so fetch-fallback
consumers have verifiable text even when the PDF fetch fails.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery

_BASE_URL = "https://api.openalex.org/works"
_SELECT = (
    "id,title,doi,publication_date,relevance_score,"
    "best_oa_location,primary_location,abstract_inverted_index"
)


def _reconstruct_abstract(inverted: dict | None) -> str:
    """Rebuild abstract text from OpenAlex's inverted index."""
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        if isinstance(idxs, list):
            positions.extend((i, word) for i in idxs if isinstance(i, int))
    positions.sort()
    return " ".join(word for _, word in positions)


def _pick_url(result: dict) -> str | None:
    """Prefer the OA PDF, then the OA landing page. None = not fetchable."""
    oa = result.get("best_oa_location") or {}
    if isinstance(oa, dict):
        for key in ("pdf_url", "landing_page_url"):
            url = oa.get(key)
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None


class OpenAlexSearchAdapter(SearchAdapter):
    """Adapter for the keyless OpenAlex scholarly works API."""

    provider_name = "openalex"

    def __init__(
        self,
        mailto: str | None = None,
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        """``mailto`` opts into OpenAlex's polite pool (recommended, optional)."""
        self.mailto = mailto
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)
            self._owns_client = True

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute an OpenAlex works search; OA-gated normalized results."""
        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError(
                "OpenAlex does not support retrieval_instruction",
                context={"provider": self.provider_name, "query": query.query},
            )
        if query.domains_allow or query.domains_deny:
            raise CapabilityNotSupportedError(
                "OpenAlex does not support domain filters",
                context={"provider": self.provider_name, "query": query.query},
            )
        params: dict[str, str] = {
            "search": query.query,
            "per-page": str(min(max(query.top_k * 2, 5), 50)),  # over-fetch: OA gate prunes
            "select": _SELECT,
        }
        if self.mailto:
            params["mailto"] = self.mailto
        if query.recency_days is not None:
            cutoff = datetime.now(timezone.utc).date().toordinal() - int(query.recency_days)
            params["filter"] = (
                f"from_publication_date:{datetime.fromordinal(cutoff).date().isoformat()}"
            )

        try:
            response = self.client.get(_BASE_URL, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "OpenAlex request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"OpenAlex returned HTTP {exc.response.status_code}",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "OpenAlex request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        raw_results = response.json().get("results", [])
        hits: list[SearchHit] = []
        rank = 0
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            url = _pick_url(result)
            if url is None:
                continue  # OA gate: never mint an unfetchable citation
            abstract = _reconstruct_abstract(result.get("abstract_inverted_index"))
            published_at = None
            pub = result.get("publication_date")
            if isinstance(pub, str) and pub:
                try:
                    published_at = datetime.fromisoformat(pub).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            source = (result.get("primary_location") or {}).get("source") or {}
            payload = dict(result)
            payload.pop("abstract_inverted_index", None)
            if len(abstract) > 100:
                payload["raw_content"] = abstract
            rank += 1
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=result.get("title"),
                    url=url,
                    snippet=abstract[:400] if abstract else None,
                    publisher=source.get("display_name") if isinstance(source, dict) else None,
                    published_at=published_at,
                    rank=rank,
                    # OpenAlex relevance_score is UNBOUNDED (BM25-ish) — never
                    # comparable to Tavily's 0-1 scale, so score_hint stays
                    # None and the raw value rides the payload. (The scaled-
                    # score landmine is a documented lesson upstream.)
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
