"""Contract tests for search adapters."""

from __future__ import annotations

import httpx
import pytest

from open_web_retrieval.adapters.brave import BraveSearchAdapter, _parse_published
from open_web_retrieval.adapters.exa import ExaSearchAdapter
from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter, _normalize_host
from open_web_retrieval.adapters.tavily import TavilySearchAdapter
from open_web_retrieval.exceptions import (
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RetrievalError,
)
from open_web_retrieval.models import SearchHit, SearchQuery


class TestBraveAdapter:
    def test_search_returns_normalized_hits(self, brave_adapter):
        query = SearchQuery(query="test", providers=("brave",), top_k=3)
        hits = brave_adapter.search(query)
        assert len(hits) == 3
        for hit in hits:
            assert isinstance(hit, SearchHit)
            assert hit.provider == "brave"
            assert hit.query == "test"
            assert hit.url == "https://example.com/article"
            assert hit.title == "Example Result"
            assert hit.snippet == "A test article about testing."

    def test_search_respects_top_k(self):
        """Adapter should truncate results to top_k."""
        results = [{"title": f"Result {i}", "url": f"https://example.com/{i}"} for i in range(20)]
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"web": {"results": results}},
                                       request=req)
        )
        adapter = BraveSearchAdapter(api_key="key", client=httpx.Client(transport=transport))
        query = SearchQuery(query="test", providers=("brave",), top_k=5)
        hits = adapter.search(query)
        assert len(hits) == 5

    def test_search_ranks_start_at_1(self, brave_adapter):
        query = SearchQuery(query="test", providers=("brave",), top_k=3)
        hits = brave_adapter.search(query)
        assert [h.rank for h in hits] == [1, 2, 3]

    def test_no_api_key_raises(self):
        with pytest.raises(ProviderUnavailableError):
            BraveSearchAdapter(api_key="")

    def test_timeout_raises_error(self):
        transport = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.TimeoutException("timeout")))
        adapter = BraveSearchAdapter(api_key="key", client=httpx.Client(transport=transport))
        query = SearchQuery(query="test", providers=("brave",))
        with pytest.raises(OpenWebRetrievalError):
            adapter.search(query)

    def test_http_error_raises_retrieval_error(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, request=req, json={"error": "rate limited"})
        )
        adapter = BraveSearchAdapter(api_key="key", client=httpx.Client(transport=transport))
        query = SearchQuery(query="test", providers=("brave",))
        with pytest.raises(RetrievalError) as exc_info:
            adapter.search(query)
        assert exc_info.value.error_code == "OPEN_WEB_RETRIEVAL_RETRIEVAL_ERROR"

    def test_invalid_json_raises(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, content=b"not json", request=req,
                                       headers={"content-type": "text/plain"})
        )
        adapter = BraveSearchAdapter(api_key="key", client=httpx.Client(transport=transport))
        query = SearchQuery(query="test", providers=("brave",))
        with pytest.raises(RetrievalError):
            adapter.search(query)

    def test_empty_results(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"web": {"results": []}}, request=req)
        )
        adapter = BraveSearchAdapter(api_key="key", client=httpx.Client(transport=transport))
        query = SearchQuery(query="test", providers=("brave",))
        hits = adapter.search(query)
        assert hits == []

    def test_published_at_parsed(self, brave_adapter):
        query = SearchQuery(query="test", providers=("brave",), top_k=1)
        hits = brave_adapter.search(query)
        assert hits[0].published_at is not None


class TestSearxNGAdapter:
    def test_search_returns_normalized_hits(self, searxng_adapter):
        query = SearchQuery(query="test", providers=("searxng",), top_k=3)
        hits = searxng_adapter.search(query)
        assert len(hits) == 3
        for hit in hits:
            assert isinstance(hit, SearchHit)
            assert hit.provider == "searxng"
            assert hit.url == "https://example.org/page"

    def test_publisher_extracted_from_url(self, searxng_adapter):
        query = SearchQuery(query="test", providers=("searxng",), top_k=1)
        hits = searxng_adapter.search(query)
        assert hits[0].publisher == "example.org"

    def test_score_hint_preserved(self, searxng_adapter):
        query = SearchQuery(query="test", providers=("searxng",), top_k=1)
        hits = searxng_adapter.search(query)
        assert hits[0].score_hint == 0.95


class TestTavilyAdapter:
    def test_search_returns_normalized_hits(self, tavily_adapter):
        query = SearchQuery(query="test", providers=("tavily",), top_k=3)
        hits = tavily_adapter.search(query)
        assert len(hits) == 3
        for hit in hits:
            assert isinstance(hit, SearchHit)
            assert hit.provider == "tavily"
            assert hit.query == "test"
            assert hit.url == "https://example.net/tavily"
            assert hit.title == "Tavily Result"
            assert hit.snippet == "Summarized content from Tavily."
            assert hit.publisher == "example.net"
            assert hit.score_hint == 0.88

    def test_no_api_key_raises(self):
        with pytest.raises(ProviderUnavailableError):
            TavilySearchAdapter(api_key="")

    def test_search_maps_domain_and_recency_filters(self):
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            captured.update(payload)
            return httpx.Response(
                200,
                json={
                    "query": payload["query"],
                    "answer": None,
                    "follow_up_questions": [],
                    "images": [],
                    "request_id": "req_test",
                    "response_time": 0.1,
                    "results": [],
                },
                request=request,
            )

        adapter = TavilySearchAdapter(
            api_key="key",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        query = SearchQuery(
            query="test",
            providers=("tavily",),
            top_k=4,
            recency_days=30,
            domains_allow=("epa.gov",),
            domains_deny=("wikipedia.org",),
        )
        hits = adapter.search(query)
        assert hits == []
        assert captured["search_depth"] == "advanced"
        assert captured["max_results"] == 4
        assert captured["include_domains"] == ["epa.gov"]
        assert captured["exclude_domains"] == ["wikipedia.org"]
        assert captured["days"] == 30


class TestExaAdapter:
    def test_search_returns_normalized_hits(self, exa_adapter):
        query = SearchQuery(query="test", providers=("exa",), top_k=3)
        hits = exa_adapter.search(query)
        assert len(hits) == 3
        for hit in hits:
            assert isinstance(hit, SearchHit)
            assert hit.provider == "exa"
            assert hit.query == "test"
            assert hit.url == "https://example.edu/exa"
            assert hit.title == "Exa Result"
            assert hit.snippet == "Deep semantic evidence excerpt."
            assert hit.publisher == "example.edu"
            assert hit.published_at is not None

    def test_no_api_key_raises(self):
        with pytest.raises(ProviderUnavailableError):
            ExaSearchAdapter(api_key="")

    def test_search_maps_domain_and_recency_filters(self):
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            captured.update(payload)
            return httpx.Response(
                200,
                json={
                    "requestId": "req_exa",
                    "resolvedSearchType": "deep",
                    "searchTime": 0.1,
                    "costDollars": {"total": 0.01},
                    "results": [],
                },
                request=request,
            )

        adapter = ExaSearchAdapter(
            api_key="key",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        query = SearchQuery(
            query="test",
            providers=("exa",),
            top_k=4,
            recency_days=30,
            domains_allow=("epa.gov",),
            domains_deny=("wikipedia.org",),
        )
        hits = adapter.search(query)
        assert hits == []
        assert captured["type"] == "deep"
        assert captured["numResults"] == 4
        assert captured["includeDomains"] == ["epa.gov"]
        assert captured["excludeDomains"] == ["wikipedia.org"]
        assert "startPublishedDate" in captured


class TestParsePublished:
    def test_iso_with_z(self):
        result = _parse_published("2026-03-20T12:00:00Z")
        assert result is not None
        assert result.year == 2026

    def test_iso_with_fractional_z(self):
        result = _parse_published("2026-03-20T12:00:00.000Z")
        assert result is not None

    def test_none_input(self):
        assert _parse_published(None) is None

    def test_empty_string(self):
        assert _parse_published("") is None

    def test_garbage(self):
        assert _parse_published("not a date") is None


class TestNormalizeHost:
    def test_standard_url(self):
        assert _normalize_host("https://example.com/path") == "example.com"

    def test_empty_url(self):
        assert _normalize_host("") is None
