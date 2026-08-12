"""@tool-decorated async search functions for llm_client tool registry.

Provides standalone async functions for each search adapter, decorated with
llm_client's @tool decorator. These register automatically in the global
tool registry on import, enabling discovery via:

    from llm_client.tools import registry
    registry.list_by_domain("web")

The underlying adapters are synchronous (httpx.Client), so each function
uses asyncio.to_thread() to avoid blocking the event loop.

Usage::

    from open_web_retrieval.adapters.tools import brave_search

    result = await brave_search(
        query="climate policy 2026",
        api_key="...",
        top_k=5,
    )
    assert result.success
    for hit in result.data:
        print(hit.url)
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from typing import cast

from llm_client.tools import tool

try:
    from data_contracts import boundary
except ImportError:
    def boundary(**kwargs):
        """No-op boundary decorator until data_contracts package exists."""
        def decorator(fn):
            return fn
        return decorator

from open_web_retrieval.adapters.brave import BraveSearchAdapter
from open_web_retrieval.adapters.exa import ExaSearchAdapter
from open_web_retrieval.adapters.openalex import OpenAlexSearchAdapter
from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter
from open_web_retrieval.adapters.tavily import TavilySearchAdapter
from open_web_retrieval.models import (
    OpenAlexQuery,
    OpenAlexSearchMode,
    SearchHit,
    SearchQuery,
)


@tool(
    name="brave_search",
    domain="web",
    description="Search the web using Brave Search API",
    cost_tier="cheap",
    goal="research-quality",
    complexity=1,
    designed_for="Fast hosted web search for general evidence gathering",
    result_type=SearchHit,
)
@boundary(
    name="open_web_retrieval.brave_search",
    version="0.1.0",
    producer="open_web_retrieval",
)
async def brave_search(
    query: str,
    api_key: str,
    *,
    top_k: int = 10,
    recency_days: int | None = None,
    locale: str | None = None,
    timeout_seconds: float | None = None,
) -> list[SearchHit]:
    """Search the web using Brave Search API and return normalized hits."""
    search_query = SearchQuery(
        query=query,
        providers=("brave",),
        top_k=top_k,
        recency_days=recency_days,
        locale=locale,
    )
    adapter = BraveSearchAdapter(api_key=api_key, timeout_seconds=timeout_seconds)
    try:
        return await asyncio.to_thread(adapter.search, search_query)
    finally:
        adapter.close()


@tool(
    name="searxng_search",
    domain="web",
    description="Search the web using a local SearxNG instance",
    cost_tier="free",
    goal="research-quality",
    complexity=1,
    designed_for="Low-cost local web search when a SearxNG instance is available",
    result_type=SearchHit,
)
@boundary(
    name="open_web_retrieval.searxng_search",
    version="0.1.0",
    producer="open_web_retrieval",
)
async def searxng_search(
    query: str,
    *,
    base_url: str = "http://localhost:8080",
    top_k: int = 10,
    recency_days: int | None = None,
    locale: str | None = None,
    timeout_seconds: float | None = None,
) -> list[SearchHit]:
    """Search the web using a local SearxNG instance and return normalized hits."""
    search_query = SearchQuery(
        query=query,
        providers=("searxng",),
        top_k=top_k,
        recency_days=recency_days,
        locale=locale,
    )
    adapter = SearxNGSearchAdapter(base_url=base_url, timeout_seconds=timeout_seconds)
    try:
        return await asyncio.to_thread(adapter.search, search_query)
    finally:
        adapter.close()


@tool(
    name="tavily_search",
    domain="web",
    description="Search the web using Tavily's hosted search API",
    cost_tier="cheap",
    goal="research-quality",
    complexity=2,
    designed_for="Hosted research search with depth and domain-filter controls",
    result_type=SearchHit,
)
@boundary(
    name="open_web_retrieval.tavily_search",
    version="0.1.0",
    producer="open_web_retrieval",
)
async def tavily_search(
    query: str,
    api_key: str,
    *,
    top_k: int = 10,
    recency_days: int | None = None,
    search_depth: str | None = None,
    result_detail: str | None = None,
    detail_budget: int | None = None,
    corpus: str | None = None,
    domains_allow: Sequence[str] = (),
    domains_deny: Sequence[str] = (),
    timeout_seconds: float | None = None,
) -> list[SearchHit]:
    """Search the web using Tavily's hosted API and return normalized hits."""
    search_query = SearchQuery(
        query=query,
        providers=("tavily",),
        top_k=top_k,
        recency_days=recency_days,
        search_depth=search_depth,
        result_detail=result_detail,
        detail_budget=detail_budget,
        corpus=corpus,
        domains_allow=domains_allow,
        domains_deny=domains_deny,
    )
    adapter = TavilySearchAdapter(api_key=api_key, timeout_seconds=timeout_seconds)
    try:
        return await asyncio.to_thread(adapter.search, search_query)
    finally:
        adapter.close()


@tool(
    name="exa_search",
    domain="web",
    description="Search the web using Exa's deep search API",
    cost_tier="moderate",
    goal="research-quality",
    complexity=3,
    designed_for="Deep semantic web search when richer recall justifies higher cost",
    result_type=SearchHit,
)
@boundary(
    name="open_web_retrieval.exa_search",
    version="0.1.0",
    producer="open_web_retrieval",
)
async def exa_search(
    query: str,
    api_key: str,
    *,
    top_k: int = 10,
    recency_days: int | None = None,
    search_depth: str | None = None,
    result_detail: str | None = None,
    detail_budget: int | None = None,
    corpus: str | None = None,
    domains_allow: Sequence[str] = (),
    domains_deny: Sequence[str] = (),
    timeout_seconds: float | None = None,
) -> list[SearchHit]:
    """Search the web using Exa's deep search API and return normalized hits."""
    search_query = SearchQuery(
        query=query,
        providers=("exa",),
        top_k=top_k,
        recency_days=recency_days,
        search_depth=search_depth,
        result_detail=result_detail,
        detail_budget=detail_budget,
        corpus=corpus,
        domains_allow=domains_allow,
        domains_deny=domains_deny,
    )
    adapter = ExaSearchAdapter(api_key=api_key, timeout_seconds=timeout_seconds)
    try:
        return await asyncio.to_thread(adapter.search, search_query)
    finally:
        adapter.close()


@tool(
    name="openalex_search",
    domain="web",
    description=(
        "Search fetchable open-access scholarly works in OpenAlex. Use keyword "
        "for precise terms, semantic for conceptual discovery, and oql for a "
        "works-only query with field, date, or Boolean constraints."
    ),
    cost_tier="free",
    goal="research-quality",
    complexity=2,
    designed_for=(
        "Contextual scholarly discovery through keyword, semantic, or structured OQL search"
    ),
    result_type=SearchHit,
)
@boundary(
    name="open_web_retrieval.openalex_search",
    version="0.1.0",
    producer="open_web_retrieval",
)
async def openalex_search(
    query: str,
    *,
    mode: str = "keyword",
    top_k: int = 10,
    recency_days: int | None = None,
    timeout_seconds: float | None = None,
) -> list[SearchHit]:
    """Search OpenAlex using the caller-selected provider-native query mode."""

    search_query = OpenAlexQuery(
        query=query,
        mode=cast(OpenAlexSearchMode, mode),
        top_k=top_k,
        recency_days=recency_days,
    )
    adapter = OpenAlexSearchAdapter(
        api_key=os.environ.get("OPENALEX_API_KEY") or None,
        timeout_seconds=timeout_seconds or 15.0,
    )
    try:
        return await asyncio.to_thread(adapter.search, search_query)
    finally:
        adapter.close()


openalex_search.__tool_input_examples__ = [
    {
        "query": "how people decide to share conspiracy claims online",
        "mode": "semantic",
        "top_k": 5,
    },
    {
        "query": "works where title/abstract has (conspiracy drivers in social media) and year >= (2020)",
        "mode": "oql",
        "top_k": 10,
    },
]


async def openalex_agent_tool(
    query: str,
    *,
    mode: str = "keyword",
    top_k: int = 10,
    timeout_seconds: float | None = None,
) -> str:
    """Search OpenAlex with agent-selected keyword, semantic, or works-only OQL.

    Use keyword for exact text, semantic for conceptual discovery, and OQL for
    field/date/nested Boolean constraints. OQL must begin with ``works`` and
    cannot group results. Put date constraints in OQL, for example
    ``and year >= (2020)``.
    """

    result = await openalex_search(
        query=query,
        mode=mode,
        top_k=top_k,
        timeout_seconds=timeout_seconds,
    )
    if not result.success:
        raise RuntimeError(result.error or "OpenAlex search failed")
    compact_hits = []
    for hit in result.data or []:
        metadata = hit.raw_payload.get("_openalex_meta", {}) if hit.raw_payload else {}
        compact_hits.append(
            {
                "provider": hit.provider,
                "mode": metadata.get("mode"),
                "query": hit.query,
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
                "publisher": hit.publisher,
                "published_at": hit.published_at.isoformat() if hit.published_at else None,
                "rank": hit.rank,
            }
        )
    return json.dumps(compact_hits, ensure_ascii=False)


openalex_agent_tool.__name__ = "openalex_search"
openalex_agent_tool.__tool_input_examples__ = openalex_search.__tool_input_examples__
