"""Shared test fixtures for open_web_retrieval."""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone

import httpx
import pytest

from open_web_retrieval.adapters.brave import BraveSearchAdapter
from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter
from open_web_retrieval.client import OpenWebRetrievalClient
from open_web_retrieval.models import SearchQuery


def _make_brave_response(results: list[dict]) -> httpx.Response:
    """Build a synthetic Brave API response."""
    payload = {"web": {"results": results}}
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
    )


def _make_searxng_response(results: list[dict]) -> httpx.Response:
    """Build a synthetic SearxNG response."""
    payload = {"results": results}
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )


def _make_html_response(html: str, url: str = "https://example.com") -> httpx.Response:
    """Build a synthetic HTML fetch response."""
    return httpx.Response(
        200,
        content=html.encode("utf-8"),
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


BRAVE_RESULT_FIXTURE = {
    "title": "Example Result",
    "url": "https://example.com/article",
    "description": "A test article about testing.",
    "profile": {"name": "Example Publisher"},
    "age": "2026-03-20T12:00:00Z",
    "lang": "en",
}

SEARXNG_RESULT_FIXTURE = {
    "title": "SearxNG Result",
    "url": "https://example.org/page",
    "content": "Content from SearxNG.",
    "published": "2026-03-20T12:00:00+00:00",
    "score": 0.95,
    "language": "en",
}

HTML_FIXTURE = """<!DOCTYPE html>
<html><head><title>Test Page</title></head>
<body><h1>Test Article</h1><p>This is the main content of the test article.</p>
<div class="sidebar">Navigation and ads</div></body></html>"""


@pytest.fixture
def brave_adapter():
    """Brave adapter with a mock HTTP client."""
    transport = httpx.MockTransport(
        lambda req: _make_brave_response([BRAVE_RESULT_FIXTURE] * 3)
    )
    client = httpx.Client(transport=transport)
    return BraveSearchAdapter(api_key="test-key", client=client)


@pytest.fixture
def searxng_adapter():
    """SearxNG adapter with a mock HTTP client."""
    transport = httpx.MockTransport(
        lambda req: _make_searxng_response([SEARXNG_RESULT_FIXTURE] * 3)
    )
    client = httpx.Client(transport=transport)
    return SearxNGSearchAdapter(base_url="http://localhost:8080", client=client)


@pytest.fixture
def fetch_client():
    """HTTP client that returns canned HTML for any URL."""
    transport = httpx.MockTransport(
        lambda req: _make_html_response(HTML_FIXTURE, str(req.url))
    )
    return httpx.Client(transport=transport)


@pytest.fixture
def owr_client(brave_adapter, searxng_adapter):
    """Fully wired OpenWebRetrievalClient with mock adapters."""
    return OpenWebRetrievalClient(
        adapters={"brave": brave_adapter, "searxng": searxng_adapter},
    )


@pytest.fixture
def search_query():
    """Standard test search query."""
    return SearchQuery(query="test query", providers=("brave",), top_k=5)


@pytest.fixture
def fake_tool_call_logger(monkeypatch):
    """Capture shared tool-call records without importing the real llm_client package."""

    records: list[object] = []

    class FakeToolCallResult:
        """Small stand-in for llm_client.observability.tool_calls.ToolCallResult."""

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_module = types.ModuleType("llm_client.observability.tool_calls")
    fake_module.ToolCallResult = FakeToolCallResult
    monkeypatch.setitem(sys.modules, "llm_client.observability.tool_calls", fake_module)

    def logger(record: object) -> None:
        records.append(record)

    return records, logger
