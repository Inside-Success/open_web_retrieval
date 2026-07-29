"""arXiv search adapter (keyless, preprint-targeted).

WHY THIS EXISTS alongside OpenAlex: OpenAlex is an OA-gated scholarly INDEX and
this package already has it. arXiv is the preprint SERVER, and in ML/AI the
relevant work is on arXiv months before it is indexed anywhere — which is
exactly the recency axis grounded-research cares about. The two overlap on
published papers and diverge completely on the last six months.

Keyless: the arXiv API (https://info.arxiv.org/help/api) needs no auth and no
account. Adapted from the equivalent client in
Inside-Success/social-research-mcp (Brian Mills), reshaped to this package's
SearchAdapter contract.

RATE DISCIPLINE: arXiv asks callers for roughly one request every three seconds
and to identify themselves. That is now ENFORCED, not merely documented - the
base class throttle serializes this provider at ~18/min (see _PROVIDER_LIMITS).
Pass ``contact`` to identify yourself as arXiv requests.

The abstract rides ``raw_payload["raw_content"]`` so a consumer holds verifiable
text even when the PDF fetch is blocked (same contract as the OpenAlex adapter).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

from open_web_retrieval.adapters.base import SearchAdapter
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery

_BASE_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _text(node: ET.Element | None) -> str:
    """Collapsed text of an Atom node; arXiv wraps titles/abstracts at 80 cols."""
    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def _parse_stamp(raw: str) -> datetime | None:
    """arXiv stamps are RFC3339 with a literal Z."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class ArxivSearchAdapter(SearchAdapter):
    """Adapter for the keyless arXiv Atom search API."""

    provider_name = "arxiv"

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
        contact: str | None = None,
    ) -> None:
        """``contact`` sets a identifying User-Agent, which arXiv requests."""
        self.contact = contact
        headers = {"User-Agent": f"open-web-retrieval ({contact})"} if contact else None
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.Client(
                timeout=timeout_seconds, follow_redirects=True, headers=headers
            )
            self._owns_client = True

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute an arXiv search; returns normalized preprint records."""
        if query.retrieval_instruction is not None:
            raise CapabilityNotSupportedError(
                "arXiv does not support retrieval_instruction",
                context={"provider": self.provider_name, "query": query.query},
            )
        if query.domains_allow or query.domains_deny:
            raise CapabilityNotSupportedError(
                "arXiv does not support domain filters",
                context={"provider": self.provider_name, "query": query.query},
            )

        # arXiv has no date filter in search_query. Recency is served by sorting
        # newest-first and pruning client-side, so we over-fetch to survive the
        # prune rather than silently returning fewer hits than asked for.
        recency = query.recency_days
        want = min(max(query.top_k, 1), 50)
        params = {
            "search_query": f"all:{query.query}",
            "start": "0",
            "max_results": str(min(want * 3, 100) if recency else want),
            "sortBy": "submittedDate" if recency else "relevance",
            "sortOrder": "descending",
        }

        try:
            with self.paced():
                response = self.client.get(_BASE_URL, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "arXiv request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"arXiv returned HTTP {exc.response.status_code}",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "arXiv request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            # arXiv answers 200 with an error body on some malformed queries —
            # fail as a retrieval error, never as an empty result set that a
            # consumer would read as "no such research exists".
            raise RetrievalError(
                "arXiv returned a body that is not valid XML",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        # Parsing is NOT enough: an HTML error page is perfectly valid XML, so it
        # parses, yields zero Atom entries, and would return [] — the silent
        # "no research exists" lie this guard exists to prevent. Caught by
        # test_non_xml_body_raises_instead_of_returning_empty.
        if root.tag != f"{_ATOM}feed":
            raise RetrievalError(
                f"arXiv returned <{root.tag}>, not an Atom feed",
                context={"provider": self.provider_name, "query": query.query},
            )

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=int(recency))
            if recency is not None
            else None
        )

        hits: list[SearchHit] = []
        rank = 0
        for entry in root.findall(f"{_ATOM}entry"):
            abs_url = _text(entry.find(f"{_ATOM}id"))
            if not abs_url.startswith("http"):
                continue
            published_at = _parse_stamp(_text(entry.find(f"{_ATOM}published")))
            if cutoff is not None and (published_at is None or published_at < cutoff):
                continue

            abstract = _text(entry.find(f"{_ATOM}summary"))
            authors = [
                _text(a.find(f"{_ATOM}name"))
                for a in entry.findall(f"{_ATOM}author")
            ]
            pdf_url = None
            for link in entry.findall(f"{_ATOM}link"):
                if link.get("title") == "pdf" and link.get("href"):
                    pdf_url = link.get("href")
                    break

            payload: dict = {
                "arxiv_abs_url": abs_url,
                "pdf_url": pdf_url,
                "authors": [a for a in authors if a],
                "updated": _text(entry.find(f"{_ATOM}updated")),
                "categories": [
                    c.get("term")
                    for c in entry.findall(f"{_ATOM}category")
                    if c.get("term")
                ],
            }
            if len(abstract) > 100:
                payload["raw_content"] = abstract

            rank += 1
            hits.append(
                SearchHit(
                    provider=self.provider_name,
                    query=query.query,
                    title=_text(entry.find(f"{_ATOM}title")) or None,
                    # The abs page, not the PDF: it is reliably fetchable, and
                    # the PDF rides the payload for a consumer that wants it.
                    url=abs_url,
                    snippet=abstract[:400] if abstract else None,
                    publisher="arXiv",
                    published_at=published_at,
                    rank=rank,
                    # arXiv returns no relevance score at all. None is the
                    # honest value; do not synthesize one from rank.
                    score_hint=None,
                    language=None,
                    raw_payload=payload,
                )
            )
            if len(hits) >= want:
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
