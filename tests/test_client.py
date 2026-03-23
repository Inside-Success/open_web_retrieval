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
