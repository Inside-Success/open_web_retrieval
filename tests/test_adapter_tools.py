"""Tests for @tool-decorated async search functions."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

llm_tools = pytest.importorskip(
    "llm_client.tools",
    reason="Brian's private llm_client checkout is required for adapter integration tests",
)
ToolResult = llm_tools.ToolResult
registry = llm_tools.registry

from open_web_retrieval.adapters.tools import (
    brave_search,
    exa_search,
    openalex_agent_tool,
    openalex_search,
    searxng_search,
    tavily_search,
)
from open_web_retrieval.models import SearchHit

# ---------------------------------------------------------------------------
# Inline mock response builders (mirror conftest fixtures)
# ---------------------------------------------------------------------------

BRAVE_RESULT = {
    "title": "Example Result",
    "url": "https://example.com/article",
    "description": "A test article about testing.",
    "profile": {"name": "Example Publisher"},
    "age": "2026-03-20T12:00:00Z",
    "lang": "en",
}

SEARXNG_RESULT = {
    "title": "SearxNG Result",
    "url": "https://example.org/page",
    "content": "Content from SearxNG.",
    "published": "2026-03-20T12:00:00+00:00",
    "score": 0.95,
    "language": "en",
}

TAVILY_RESULT = {
    "title": "Tavily Result",
    "url": "https://example.net/tavily",
    "content": "Summarized content from Tavily.",
    "score": 0.88,
    "raw_content": None,
}

EXA_RESULT = {
    "title": "Exa Result",
    "url": "https://example.edu/exa",
    "publishedDate": "2026-03-20T12:00:00Z",
    "highlights": ["Deep semantic evidence excerpt."],
    "highlightScores": [0.91],
}


def _brave_response(results: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"web": {"results": results}},
        request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
    )


def _searxng_response(results: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"results": results},
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )


def _tavily_response(results: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "query": "test",
            "answer": None,
            "follow_up_questions": [],
            "images": [],
            "request_id": "req_test",
            "response_time": 0.1,
            "results": results,
        },
        request=httpx.Request("POST", "https://api.tavily.com/search"),
    )


def _exa_response(results: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "requestId": "req_exa",
            "resolvedSearchType": "deep",
            "searchTime": 0.1,
            "costDollars": {"total": 0.01},
            "results": results,
        },
        request=httpx.Request("POST", "https://api.exa.ai/search"),
    )


def _patch_transport(transport: httpx.MockTransport):
    """Return a context manager that injects *transport* into all new httpx.Client instances."""
    original = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    return patch.object(httpx.Client, "__init__", patched_init)


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all four tools register in the global registry."""

    def test_brave_registered(self):
        info = registry.get("brave_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "cheap"
        assert info.goal == "research-quality"
        assert info.complexity == 1
        assert info.designed_for == "Fast hosted web search for general evidence gathering"

    def test_searxng_registered(self):
        info = registry.get("searxng_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "free"
        assert info.goal == "research-quality"
        assert info.complexity == 1

    def test_tavily_registered(self):
        info = registry.get("tavily_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "cheap"
        assert info.goal == "research-quality"
        assert info.complexity == 2

    def test_exa_registered(self):
        info = registry.get("exa_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "moderate"
        assert info.goal == "research-quality"
        assert info.complexity == 3

    def test_openalex_registered_with_contextual_mode_guidance(self):
        info = registry.get("openalex_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "free"
        assert info.goal == "research-quality"
        assert info.complexity == 2
        assert info.designed_for is not None
        assert "keyword, semantic, or structured OQL" in info.designed_for

    def test_list_by_domain_returns_all_search_tools(self):
        web_tools = registry.list_by_domain("web")
        names = {t.name for t in web_tools}
        assert names >= {
            "brave_search",
            "searxng_search",
            "tavily_search",
            "exa_search",
            "openalex_search",
        }


# ---------------------------------------------------------------------------
# Functional tests — each tool returns ToolResult wrapping SearchHit list
# ---------------------------------------------------------------------------


class TestBraveSearchTool:
    @pytest.mark.asyncio
    async def test_returns_tool_result_with_hits(self):
        transport = httpx.MockTransport(lambda req: _brave_response([BRAVE_RESULT] * 2))
        with _patch_transport(transport):
            result = await brave_search(query="test query", api_key="test-key", top_k=2)

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "brave_search"
        assert len(result.data) == 2
        assert all(isinstance(h, SearchHit) for h in result.data)
        assert all(h.provider == "brave" for h in result.data)

    @pytest.mark.asyncio
    async def test_error_wrapped_in_tool_result(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(401, request=req, json={"error": "bad key"})
        )
        with _patch_transport(transport):
            result = await brave_search(query="test", api_key="bad-key")

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_latency_recorded(self):
        transport = httpx.MockTransport(lambda req: _brave_response([BRAVE_RESULT]))
        with _patch_transport(transport):
            result = await brave_search(query="test", api_key="k")
        assert result.latency_s >= 0.0


class TestSearxNGSearchTool:
    @pytest.mark.asyncio
    async def test_returns_tool_result_with_hits(self):
        transport = httpx.MockTransport(lambda req: _searxng_response([SEARXNG_RESULT] * 3))
        with _patch_transport(transport):
            result = await searxng_search(query="test query", top_k=3)

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "searxng_search"
        assert len(result.data) == 3
        assert all(h.provider == "searxng" for h in result.data)


class TestTavilySearchTool:
    @pytest.mark.asyncio
    async def test_returns_tool_result_with_hits(self):
        transport = httpx.MockTransport(lambda req: _tavily_response([TAVILY_RESULT] * 2))
        with _patch_transport(transport):
            result = await tavily_search(query="test", api_key="test-key", top_k=2)

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "tavily_search"
        assert len(result.data) == 2
        assert all(h.provider == "tavily" for h in result.data)


class TestExaSearchTool:
    @pytest.mark.asyncio
    async def test_returns_tool_result_with_hits(self):
        transport = httpx.MockTransport(lambda req: _exa_response([EXA_RESULT] * 2))
        with _patch_transport(transport):
            result = await exa_search(query="test", api_key="test-key", top_k=2)

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "exa_search"
        assert len(result.data) == 2
        assert all(h.provider == "exa" for h in result.data)
        assert all(h.published_at is not None for h in result.data)


class TestOpenAlexSearchTool:
    def test_existing_agent_runtime_can_build_the_tool_schema(self):
        from llm_client.tools.tool_utils import callable_to_openai_tool

        schema = callable_to_openai_tool(openalex_agent_tool)
        function = schema["function"]
        assert function["name"] == "openalex_search"
        assert function["parameters"]["properties"]["mode"]["type"] == "string"
        assert "recency_days" not in function["parameters"]["properties"]
        assert "semantic" in function["description"]
        assert "works where title/abstract has" in function["description"]

    @pytest.mark.asyncio
    async def test_direct_agent_tool_returns_json_serializable_hits(self, monkeypatch):
        import json

        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "meta": {"cost_usd": 0.001},
                    "results": [{
                        "id": "https://openalex.org/W1",
                        "title": "Contextual tool selection",
                        "publication_date": "2026-03-20",
                        "best_oa_location": {
                            "pdf_url": "https://papers.example/1.pdf",
                        },
                        "primary_location": {
                            "source": {"display_name": "Agent Studies"},
                        },
                        "abstract_inverted_index": {
                            "Agents": [0],
                            "choose": [1],
                            "contextual": [2],
                            "research": [3],
                            "tools": [4],
                            "using": [5],
                            "explicit": [6],
                            "goals": [7],
                            "and": [8],
                            "provider": [9],
                            "constraints": [10],
                            "while": [11],
                            "preserving": [12],
                            "provenance": [13],
                            "for": [14],
                            "downstream": [15],
                            "evidence": [16],
                            "recovery": [17],
                            "when": [18],
                            "publisher": [19],
                            "pages": [20],
                            "are": [21],
                            "blocked": [22],
                        },
                    }],
                },
                request=request,
            )

        with _patch_transport(httpx.MockTransport(handler)):
            raw = await openalex_agent_tool(
                query="how agents choose research tools from context",
                mode="semantic",
                top_k=1,
            )

        payload = json.loads(raw)
        assert payload[0]["provider"] == "openalex"
        assert payload[0]["mode"] == "semantic"
        assert payload[0]["title"] == "Contextual tool selection"
        assert payload[0]["raw_content"].startswith("Agents choose contextual")

    @pytest.mark.asyncio
    async def test_semantic_mode_returns_normalized_hits(self, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "meta": {"cost_usd": 0.001},
                    "results": [{
                        "id": "https://openalex.org/W1",
                        "title": "Contextual tool selection",
                        "publication_date": "2026-03-20",
                        "best_oa_location": {
                            "pdf_url": "https://papers.example/1.pdf",
                        },
                        "primary_location": {
                            "source": {"display_name": "Agent Studies"},
                        },
                        "abstract_inverted_index": None,
                    }],
                },
                request=request,
            )

        with _patch_transport(httpx.MockTransport(handler)):
            result = await openalex_search(
                query="how agents choose research tools from context",
                mode="semantic",
                top_k=1,
            )

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "openalex_search"
        assert len(result.data) == 1
        assert result.data[0].provider == "openalex"
        assert "search.semantic" in requests[0].url.params

    @pytest.mark.asyncio
    async def test_oql_validation_failure_makes_zero_requests(self):
        requests: list[httpx.Request] = []
        transport = httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, request=request),
        )
        with _patch_transport(transport):
            result = await openalex_search(
                query="authors where works_count > (10)",
                mode="oql",
            )

        assert result.success is False
        assert requests == []
