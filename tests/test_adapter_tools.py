"""Tests for @tool-decorated async search functions."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from llm_client.tools import ToolResult, registry

from open_web_retrieval.adapters.tools import (
    brave_search,
    exa_search,
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

    def test_searxng_registered(self):
        info = registry.get("searxng_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "free"

    def test_tavily_registered(self):
        info = registry.get("tavily_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "cheap"

    def test_exa_registered(self):
        info = registry.get("exa_search")
        assert info is not None
        assert info.domain == "web"
        assert info.cost_tier == "moderate"

    def test_list_by_domain_returns_all_four(self):
        web_tools = registry.list_by_domain("web")
        names = {t.name for t in web_tools}
        assert names >= {"brave_search", "searxng_search", "tavily_search", "exa_search"}


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
