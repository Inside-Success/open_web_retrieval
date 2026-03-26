"""Contract tests for OpenWebRetrievalClient orchestrator."""

from __future__ import annotations

import httpx
import pytest

from open_web_retrieval.adapters.brave import BraveSearchAdapter
from open_web_retrieval.client import OpenWebRetrievalClient, SourceRecordBatch
from open_web_retrieval.exceptions import (
    OpenWebRetrievalError,
    ProviderUnavailableError,
)
from open_web_retrieval.models import SearchHit, SearchQuery


class TestClientInit:
    def test_no_providers_raises(self):
        with pytest.raises(ProviderUnavailableError):
            OpenWebRetrievalClient()

    def test_brave_only(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"web": {"results": []}}, request=req)
        )
        client = OpenWebRetrievalClient(
            adapters={"brave": BraveSearchAdapter(
                api_key="key", client=httpx.Client(transport=transport)
            )},
        )
        assert "brave" in client.default_providers


class TestClientSearch:
    def test_search_returns_hits(self, owr_client, search_query):
        hits = owr_client.search(search_query)
        assert len(hits) > 0
        assert all(isinstance(h, SearchHit) for h in hits)

    def test_search_respects_top_k(self, owr_client):
        query = SearchQuery(query="test", providers=("brave",), top_k=2)
        hits = owr_client.search(query)
        assert len(hits) <= 2

    def test_search_missing_provider_graceful(self, owr_client):
        """If one provider is missing but another works, search succeeds."""
        # owr_client has brave and searxng; asking for just brave should work
        query = SearchQuery(query="test", providers=("brave",))
        hits = owr_client.search(query)
        assert len(hits) > 0

    def test_search_all_missing_raises(self):
        """If all requested providers are unconfigured, raise."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"web": {"results": []}}, request=req)
        )
        # Client only has brave configured
        client = OpenWebRetrievalClient(
            adapters={"brave": BraveSearchAdapter(
                api_key="key", client=httpx.Client(transport=transport)
            )},
        )
        # But query asks for searxng only
        query = SearchQuery(query="test", providers=("searxng",))
        with pytest.raises(ProviderUnavailableError):
            client.search(query)


class TestClientRetrieve:
    def test_retrieve_returns_batch(self, owr_client, search_query):
        # The owr_client fixture doesn't have a fetch client wired,
        # so retrieve will fail on fetch. Use allow_partial.
        batch = owr_client.retrieve(search_query, allow_partial=True)
        assert isinstance(batch, SourceRecordBatch)
        assert batch.query == search_query
        assert len(batch.records) > 0

    def test_retrieve_partial_captures_errors(self, owr_client, search_query):
        batch = owr_client.retrieve(search_query, allow_partial=True)
        # Some records may have fetch errors in provenance
        for record in batch.records:
            assert record.search_hit is not None
            if record.fetched_resource is None:
                assert "error" in record.provenance

    def test_retrieve_strict_raises_on_fetch_failure(self, owr_client, search_query):
        # Without allow_partial, fetch failures should propagate
        with pytest.raises(Exception):
            owr_client.retrieve(search_query, allow_partial=False)

    def test_retrieve_emits_search_fetch_extract_tool_calls(self, brave_adapter, fetch_client, fake_tool_call_logger):
        records, logger = fake_tool_call_logger
        client = OpenWebRetrievalClient(
            adapters={"brave": brave_adapter},
            tool_call_logger=logger,
        )
        client.fetcher.client = fetch_client
        client.fetcher._owns_client = False

        query = SearchQuery(query="ubi pilot programs", providers=("brave",), top_k=1)
        batch = client.retrieve(query, allow_partial=False, trace_id="trace_owr_1", task="collect")

        assert len(batch.records) == 1
        operations = [(record.operation, record.status) for record in records]
        assert ("search", "started") in operations
        assert ("search", "succeeded") in operations
        assert ("fetch", "started") in operations
        assert ("fetch", "succeeded") in operations
        assert ("extract", "started") in operations
        assert ("extract", "succeeded") in operations
        assert all(record.trace_id == "trace_owr_1" for record in records)


class TestClientExceptions:
    def test_error_codes_are_stable(self):
        """Error codes are part of the public contract — don't change them."""
        from open_web_retrieval.exceptions import (
            CapabilityNotSupportedError,
            FetchError,
            OpenWebRetrievalError,
            ProviderUnavailableError,
            RenderError,
            RetrievalError,
        )
        assert OpenWebRetrievalError.error_code == "OPEN_WEB_RETRIEVAL_ERROR"
        assert ProviderUnavailableError.error_code == "OPEN_WEB_RETRIEVAL_PROVIDER_UNAVAILABLE"
        assert RetrievalError.error_code == "OPEN_WEB_RETRIEVAL_RETRIEVAL_ERROR"
        assert FetchError.error_code == "OPEN_WEB_RETRIEVAL_FETCH_ERROR"
        assert RenderError.error_code == "OPEN_WEB_RETRIEVAL_RENDER_ERROR"
        assert CapabilityNotSupportedError.error_code == "OPEN_WEB_RETRIEVAL_CAPABILITY_UNSUPPORTED"

    def test_error_context_preserved(self):
        err = ProviderUnavailableError("test", context={"key": "value"})
        assert err.context["key"] == "value"
        assert str(err) == "test"


class TestSearchDedup:
    """Tests for search result deduplication by URL (Plan #03)."""

    def test_search_dedup_by_url(self):
        """Duplicate URLs from two providers are kept only once."""
        import httpx
        from open_web_retrieval.adapters.brave import BraveSearchAdapter
        from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter

        # Both providers return a result with the same URL
        brave_results = [{
            "title": "Brave Result",
            "url": "https://example.com/shared",
            "description": "From Brave",
        }]
        searxng_results = [{
            "title": "SearxNG Result",
            "url": "https://example.com/shared",
            "content": "From SearxNG",
        }]

        brave_transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"web": {"results": brave_results}}, request=req)
        )
        searxng_transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"results": searxng_results}, request=req)
        )

        client = OpenWebRetrievalClient(
            adapters={
                "brave": BraveSearchAdapter(
                    api_key="key", client=httpx.Client(transport=brave_transport)
                ),
                "searxng": SearxNGSearchAdapter(
                    base_url="http://localhost:8080", client=httpx.Client(transport=searxng_transport)
                ),
            },
        )

        query = SearchQuery(query="test", providers=("brave", "searxng"), top_k=10)
        hits = client.search(query)

        # Should have only 1 hit, not 2
        urls = [h.url for h in hits]
        assert len(urls) == 1, f"Expected 1 deduped hit, got {len(urls)}: {urls}"
        assert urls[0] == "https://example.com/shared"

    def test_search_dedup_preserves_order(self):
        """First occurrence (from first provider) wins in deduplication."""
        import httpx
        from open_web_retrieval.adapters.brave import BraveSearchAdapter
        from open_web_retrieval.adapters.searxng import SearxNGSearchAdapter

        brave_results = [
            {"title": "Brave First", "url": "https://example.com/shared", "description": "B"},
            {"title": "Brave Unique", "url": "https://example.com/brave-only", "description": "B"},
        ]
        searxng_results = [
            {"title": "SearxNG Dupe", "url": "https://example.com/shared", "content": "S"},
            {"title": "SearxNG Unique", "url": "https://example.com/searxng-only", "content": "S"},
        ]

        brave_transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"web": {"results": brave_results}}, request=req)
        )
        searxng_transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"results": searxng_results}, request=req)
        )

        client = OpenWebRetrievalClient(
            adapters={
                "brave": BraveSearchAdapter(
                    api_key="key", client=httpx.Client(transport=brave_transport)
                ),
                "searxng": SearxNGSearchAdapter(
                    base_url="http://localhost:8080", client=httpx.Client(transport=searxng_transport)
                ),
            },
        )

        query = SearchQuery(query="test", providers=("brave", "searxng"), top_k=10)
        hits = client.search(query)

        # 3 unique URLs: shared (from brave), brave-only, searxng-only
        urls = [h.url for h in hits]
        assert len(urls) == 3, f"Expected 3 deduped hits, got {len(urls)}: {urls}"
        # First occurrence of shared URL should be from brave
        shared_hit = [h for h in hits if h.url == "https://example.com/shared"][0]
        assert shared_hit.provider == "brave", "First occurrence (brave) should win"
        # Order preserved: brave hits first, then unique searxng hits
        assert urls[0] == "https://example.com/shared"
        assert urls[1] == "https://example.com/brave-only"
        assert urls[2] == "https://example.com/searxng-only"
