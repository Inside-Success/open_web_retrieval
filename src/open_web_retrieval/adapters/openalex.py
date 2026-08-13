"""OpenAlex scholarly works search with keyword, semantic, and OQL modes.

Source-ported from ``Inside-Success/open_web_retrieval`` at
``98e54bfed2c0366ce8c8e64a59d80de41e8aa917`` and revised for OpenAlex's
current API, native semantic search, works-only OQL, optional bearer
authentication, shared pacing, and the canonical upstream contracts.
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
from open_web_retrieval.models import OpenAlexQuery, SearchHit, SearchQuery

_WORKS_URL = "https://api.openalex.org/works"
_OQL_URL = "https://api.openalex.org/"
_SELECT_FIELDS = (
    "id,title,doi,publication_date,relevance_score,best_oa_location,"
    "primary_location,abstract_inverted_index"
)


class OpenAlexSearchAdapter(SearchAdapter):
    """Search OpenAlex works and return only fetchable open-access records."""

    provider_name = "openalex"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float | None = 15.0,
        client: httpx.Client | None = None,
        request_throttle: ProviderThrottle | None = None,
    ) -> None:
        """Configure optional bearer authentication, transport, and pacing."""

        self.api_key = api_key or None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._provider_throttle = request_throttle

    def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute one keyword, semantic, or works-only OQL query."""

        openalex_query = _normalize_query(query)
        _reject_unsupported_controls(openalex_query)
        headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key is not None
            else None
        )

        try:
            with self.paced():
                if openalex_query.mode == "oql":
                    response = self.client.post(
                        _OQL_URL,
                        json={
                            "oql": openalex_query.query,
                            "select": _SELECT_FIELDS,
                            "per_page": min(max(openalex_query.top_k * 2, 5), 100),
                        },
                        headers=headers,
                    )
                else:
                    response = self.client.get(
                        _WORKS_URL,
                        params=_search_params(openalex_query),
                        headers=headers,
                    )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise OpenWebRetrievalError(
                "OpenAlex request timed out",
                context={
                    "provider": self.provider_name,
                    "query": openalex_query.query,
                    "mode": openalex_query.mode,
                },
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RetrievalError(
                f"OpenAlex returned HTTP {exc.response.status_code}",
                context={
                    "provider": self.provider_name,
                    "query": openalex_query.query,
                    "mode": openalex_query.mode,
                    "status_code": exc.response.status_code,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenWebRetrievalError(
                "OpenAlex request failed",
                context={
                    "provider": self.provider_name,
                    "query": openalex_query.query,
                    "mode": openalex_query.mode,
                },
            ) from exc
        except ValueError as exc:
            raise RetrievalError(
                "OpenAlex returned invalid JSON",
                context={
                    "provider": self.provider_name,
                    "query": openalex_query.query,
                    "mode": openalex_query.mode,
                },
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise RetrievalError(
                "OpenAlex response did not contain a results list",
                context={
                    "provider": self.provider_name,
                    "query": openalex_query.query,
                    "mode": openalex_query.mode,
                },
            )
        raw_meta = payload.get("meta")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        return _normalize_results(
            payload["results"],
            query=openalex_query,
            meta=meta,
        )

    def close(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            self.client.close()

    # ``typing.Self`` is unavailable on the package's Python 3.10 floor.
    def __enter__(self) -> OpenAlexSearchAdapter:  # noqa: PYI034
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


def _normalize_query(query: SearchQuery) -> OpenAlexQuery:
    """Promote the shared query to OpenAlex's default keyword contract."""

    if isinstance(query, OpenAlexQuery):
        return query
    return OpenAlexQuery(**query.model_dump())


def _reject_unsupported_controls(query: OpenAlexQuery) -> None:
    """Fail before HTTP when shared controls have no OpenAlex mapping."""

    unsupported = {
        "locale": query.locale,
        "search_depth": query.search_depth,
        "result_detail": query.result_detail,
        "detail_budget": query.detail_budget,
        "corpus": query.corpus,
        "retrieval_instruction": query.retrieval_instruction,
        "domains_allow": tuple(query.domains_allow),
        "domains_deny": tuple(query.domains_deny),
    }
    active = sorted(name for name, value in unsupported.items() if value not in (None, ()))
    if active:
        raise CapabilityNotSupportedError(
            f"OpenAlex does not support shared control(s): {', '.join(active)}",
            context={
                "provider": "openalex",
                "query": query.query,
                "unsupported_controls": active,
            },
        )


def _search_params(query: OpenAlexQuery) -> dict[str, str]:
    """Build current OpenAlex works parameters without exposing credentials."""

    search_parameter = "search.semantic" if query.mode == "semantic" else "search"
    filters = ["is_oa:true"]
    if query.recency_days is not None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=query.recency_days)
        filters.append(f"from_publication_date:{cutoff.isoformat()}")
    return {
        search_parameter: query.query,
        "filter": ",".join(filters),
        "per-page": str(min(max(query.top_k * 2, 5), 100)),
        "select": _SELECT_FIELDS,
    }


def _normalize_results(
    raw_results: list[object],
    *,
    query: OpenAlexQuery,
    meta: dict[str, Any],
) -> list[SearchHit]:
    """Normalize OpenAlex works while retaining provider query provenance."""

    hits: list[SearchHit] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        url = _pick_open_access_url(result)
        if url is None:
            continue
        abstract = _reconstruct_abstract(result.get("abstract_inverted_index"))
        payload = dict(result)
        payload.pop("abstract_inverted_index", None)
        if len(abstract) > 100:
            payload["raw_content"] = abstract
        payload["_openalex_meta"] = {
            "mode": query.mode,
            "cost_usd": meta.get("cost_usd"),
            "x_query": meta.get("x_query"),
        }
        primary_location = result.get("primary_location")
        source = (
            primary_location.get("source")
            if isinstance(primary_location, dict)
            else None
        )
        publisher = source.get("display_name") if isinstance(source, dict) else None

        hits.append(
            SearchHit(
                provider="openalex",
                query=query.query,
                title=_optional_string(result.get("title")),
                url=url,
                snippet=abstract[:400] or None,
                publisher=_optional_string(publisher),
                published_at=_parse_publication_date(result.get("publication_date")),
                rank=len(hits) + 1,
                # OpenAlex keyword relevance and semantic cosine scores do not
                # share one normalized cross-provider scale.
                score_hint=None,
                language=None,
                raw_payload=payload,
            ),
        )
        if len(hits) >= query.top_k:
            break
    return hits


def _pick_open_access_url(result: dict[str, Any]) -> str | None:
    """Prefer the best open PDF, then its open landing page."""

    location = result.get("best_oa_location")
    if not isinstance(location, dict):
        return None
    for field in ("pdf_url", "landing_page_url"):
        value = location.get(field)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _reconstruct_abstract(value: object) -> str:
    """Rebuild readable abstract text from OpenAlex's inverted index."""

    if not isinstance(value, dict):
        return ""
    positioned_words: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        positioned_words.extend(
            (position, word)
            for position in positions
            if isinstance(position, int)
        )
    positioned_words.sort()
    return " ".join(word for _, word in positioned_words)


def _parse_publication_date(value: object) -> datetime | None:
    """Parse an OpenAlex date as an aware UTC timestamp."""

    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _optional_string(value: object) -> str | None:
    """Return non-empty provider strings only."""

    return value if isinstance(value, str) and value else None
