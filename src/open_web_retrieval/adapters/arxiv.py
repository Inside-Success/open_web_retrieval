"""Keyless, source-targeted arXiv search adapter.

Source-ported from ``Inside-Success/open_web_retrieval`` at
``98e54bfed2c0366ce8c8e64a59d80de41e8aa917`` with contract and testability
adaptations for the canonical upstream.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
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

_BASE_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivSearchAdapter(SearchAdapter):
    """Search the public arXiv Atom API and normalize preprint records."""

    provider_name = "arxiv"

    def __init__(
        self,
        *,
        timeout_seconds: float | None = 20.0,
        contact: str | None = None,
        client: httpx.Client | None = None,
        request_throttle: ProviderThrottle | None = None,
    ) -> None:
        """Configure transport, optional contact identity, and pacing."""

        self.user_agent = f"open-web-retrieval ({contact})" if contact else None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._provider_throttle = request_throttle

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Return normalized arXiv preprints for a search query."""

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

        overfetch = min(query.top_k * 3, 100) if query.recency_days else query.top_k
        params = {
            "search_query": f"all:{query.query}",
            "start": "0",
            "max_results": str(overfetch),
            "sortBy": "submittedDate" if query.recency_days else "relevance",
            "sortOrder": "descending",
        }
        headers = {"User-Agent": self.user_agent} if self.user_agent else None

        try:
            with self.paced():
                response = self.client.get(_BASE_URL, params=params, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "arXiv request timed out",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"arXiv returned HTTP {exc.response.status_code}",
                context={
                    "provider": self.provider_name,
                    "query": query.query,
                    "status_code": exc.response.status_code,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "arXiv request failed",
                context={"provider": self.provider_name, "query": query.query},
            ) from exc

        root = _parse_feed(response.text, query)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=query.recency_days)
            if query.recency_days is not None
            else None
        )

        hits: list[SearchHit] = []
        for entry in root.findall(f"{_ATOM}entry"):
            absolute_url = _text(entry.find(f"{_ATOM}id"))
            if not absolute_url.startswith(("http://", "https://")):
                continue
            published_at = _parse_timestamp(_text(entry.find(f"{_ATOM}published")))
            if cutoff is not None and (
                published_at is None or published_at < cutoff
            ):
                continue

            abstract = _text(entry.find(f"{_ATOM}summary"))
            authors = [
                _text(author.find(f"{_ATOM}name"))
                for author in entry.findall(f"{_ATOM}author")
            ]
            pdf_url = next(
                (
                    link.get("href")
                    for link in entry.findall(f"{_ATOM}link")
                    if link.get("title") == "pdf" and link.get("href")
                ),
                None,
            )
            raw_payload: dict[str, Any] = {
                "arxiv_abs_url": absolute_url,
                "pdf_url": pdf_url,
                "authors": [author for author in authors if author],
                "updated": _text(entry.find(f"{_ATOM}updated")),
                "categories": [
                    category.get("term")
                    for category in entry.findall(f"{_ATOM}category")
                    if category.get("term")
                ],
            }
            if len(abstract) > 100:
                raw_payload["raw_content"] = abstract

            hits.append(
                SearchHit(
                    provider="arxiv",
                    query=query.query,
                    title=_text(entry.find(f"{_ATOM}title")) or None,
                    url=absolute_url,
                    snippet=abstract[:400] or None,
                    publisher="arXiv",
                    published_at=published_at,
                    rank=len(hits) + 1,
                    score_hint=None,
                    language=None,
                    raw_payload=raw_payload,
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
    def __enter__(self) -> ArxivSearchAdapter:  # noqa: PYI034
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


def _parse_feed(body: str, query: SearchQuery) -> ET.Element:
    """Parse and validate an arXiv Atom feed without treating HTML as empty."""

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RetrievalError(
            "arXiv returned a body that is not valid XML",
            context={"provider": "arxiv", "query": query.query},
        ) from exc
    if root.tag != f"{_ATOM}feed":
        raise RetrievalError(
            f"arXiv returned <{root.tag}>, not an Atom feed",
            context={"provider": "arxiv", "query": query.query},
        )
    return root


def _text(node: ET.Element | None) -> str:
    """Collapse provider line wrapping in one Atom text node."""

    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an arXiv RFC3339 timestamp into an aware UTC datetime."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc,
        )
    except ValueError:
        return None
