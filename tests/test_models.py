"""Contract tests for Pydantic models — schema validation, immutability, round-trip."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from open_web_retrieval.models import (
    ExtractedDocument,
    FetchRequest,
    FetchedResource,
    SearchHit,
    SearchQuery,
    SourceRecord,
)


class TestSearchQuery:
    def test_defaults(self):
        q = SearchQuery(query="test")
        assert q.top_k == 10
        assert "brave" in q.providers
        assert q.recency_days is None

    def test_frozen(self):
        q = SearchQuery(query="test")
        with pytest.raises(Exception):
            q.query = "mutated"

    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            SearchQuery(query="")

    def test_empty_providers_rejected(self):
        with pytest.raises(Exception):
            SearchQuery(query="test", providers=())

    def test_top_k_bounds(self):
        with pytest.raises(Exception):
            SearchQuery(query="test", top_k=0)
        with pytest.raises(Exception):
            SearchQuery(query="test", top_k=100)

    def test_duplicate_providers_deduplicated(self):
        q = SearchQuery(query="test", providers=("brave", "brave", "searxng"))
        assert q.providers == ("brave", "searxng")

    def test_recency_days_positive(self):
        with pytest.raises(Exception):
            SearchQuery(query="test", recency_days=0)

    def test_domain_filters(self):
        q = SearchQuery(
            query="test",
            domains_allow=("example.com",),
            domains_deny=("spam.com",),
        )
        assert "example.com" in q.domains_allow
        assert "spam.com" in q.domains_deny

    def test_round_trip_json(self):
        q = SearchQuery(query="test query", providers=("brave",), top_k=5)
        data = q.model_dump()
        q2 = SearchQuery(**data)
        assert q == q2


class TestSearchHit:
    def test_minimal(self):
        hit = SearchHit(provider="brave", query="test", url="https://example.com")
        assert hit.rank == 0
        assert hit.title is None
        assert hit.snippet is None

    def test_frozen(self):
        hit = SearchHit(provider="brave", query="test", url="https://example.com")
        with pytest.raises(Exception):
            hit.url = "https://mutated.com"

    def test_full_fields(self):
        now = datetime.now(tz=timezone.utc)
        hit = SearchHit(
            provider="brave",
            query="test",
            title="Title",
            url="https://example.com",
            snippet="Snippet",
            publisher="Publisher",
            published_at=now,
            rank=1,
            score_hint=0.9,
            language="en",
            raw_payload={"key": "value"},
        )
        assert hit.published_at == now
        assert hit.raw_payload["key"] == "value"


class TestFetchRequest:
    def test_defaults(self):
        req = FetchRequest(url="https://example.com")
        assert req.render_mode == "auto"
        assert req.max_bytes == 8_000_000

    def test_max_bytes_bounds(self):
        with pytest.raises(Exception):
            FetchRequest(url="https://example.com", max_bytes=0)
        with pytest.raises(Exception):
            FetchRequest(url="https://example.com", max_bytes=100_000_000)


class TestFetchedResource:
    def test_construction(self):
        now = datetime.now(tz=timezone.utc)
        res = FetchedResource(
            requested_url="https://example.com",
            final_url="https://example.com/redirected",
            status=200,
            content_type="text/html",
            content_bytes=b"<html>test</html>",
            retrieved_at_utc=now,
            sha256="abc123",
        )
        assert res.fetch_method == "httpx"
        assert res.status == 200

    def test_frozen(self):
        now = datetime.now(tz=timezone.utc)
        res = FetchedResource(
            requested_url="https://example.com",
            final_url="https://example.com",
            status=200,
            content_bytes=b"test",
            retrieved_at_utc=now,
            sha256="abc",
        )
        with pytest.raises(Exception):
            res.status = 404


class TestExtractedDocument:
    def test_construction(self):
        doc = ExtractedDocument(
            source_url="https://example.com",
            final_url="https://example.com",
            text="Extracted text",
            document_type="html",
            extraction_method="trafilatura",
        )
        assert doc.warnings == []
        assert doc.title is None

    def test_with_warnings(self):
        doc = ExtractedDocument(
            source_url="https://example.com",
            final_url="https://example.com",
            text="",
            document_type="html",
            extraction_method="fallback_strip",
            warnings=["empty body"],
        )
        assert len(doc.warnings) == 1


class TestSourceRecord:
    def test_minimal(self):
        hit = SearchHit(provider="brave", query="test", url="https://example.com")
        record = SourceRecord(query="test", search_hit=hit)
        assert record.fetched_resource is None
        assert record.extracted_document is None
        assert record.provenance == {}
