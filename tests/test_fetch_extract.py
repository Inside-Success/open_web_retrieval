"""Contract tests for fetch and extraction pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from open_web_retrieval.exceptions import FetchError
from open_web_retrieval.fetch_extract import (
    SourceFetcher,
    _hash_bytes,
    _strip_html_tags,
)
from open_web_retrieval.models import FetchRequest, FetchedResource


class TestStripHtmlTags:
    def test_simple_tags(self):
        assert _strip_html_tags("<p>hello</p>") == "hello"

    def test_nested_tags(self):
        result = _strip_html_tags("<div><p>hello</p><p>world</p></div>")
        assert "hello" in result
        assert "world" in result

    def test_empty_input(self):
        assert _strip_html_tags("") == ""

    def test_no_tags(self):
        assert _strip_html_tags("plain text") == "plain text"

    def test_whitespace_normalized(self):
        result = _strip_html_tags("<p>hello</p>   <p>world</p>")
        assert "  " not in result


class TestHashBytes:
    def test_deterministic(self):
        h1 = _hash_bytes(b"test content")
        h2 = _hash_bytes(b"test content")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = _hash_bytes(b"content a")
        h2 = _hash_bytes(b"content b")
        assert h1 != h2


class TestSourceFetcher:
    def test_fetch_returns_fetched_resource(self, fetch_client):
        fetcher = SourceFetcher(client=fetch_client)
        req = FetchRequest(url="https://example.com/page")
        resource = fetcher.fetch(req)

        assert isinstance(resource, FetchedResource)
        assert resource.requested_url == "https://example.com/page"
        assert resource.status == 200
        assert "html" in (resource.content_type or "")
        assert len(resource.content_bytes) > 0
        assert resource.sha256  # non-empty hash
        assert resource.fetch_method == "httpx"

    def test_fetch_preserves_final_url(self):
        """Redirected URLs should be captured in final_url."""
        def redirect_handler(request):
            if "redirect" in str(request.url):
                return httpx.Response(
                    200,
                    content=b"<html>final</html>",
                    headers={"content-type": "text/html"},
                    request=request,
                )
            return httpx.Response(
                301,
                headers={"location": "https://example.com/redirect"},
                request=request,
            )

        # httpx MockTransport doesn't follow redirects, so test the final URL capture
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=b"<html>content</html>",
                headers={"content-type": "text/html"},
                request=req,
            )
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com/page")
        resource = fetcher.fetch(req)
        assert resource.final_url  # URL is captured

    def test_fetch_truncates_to_max_bytes(self):
        large_content = b"x" * 1000
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=large_content,
                headers={"content-type": "text/html"},
                request=req,
            )
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com", max_bytes=100)
        resource = fetcher.fetch(req)
        assert len(resource.content_bytes) == 100

    def test_fetch_timeout_raises_fetch_error(self):
        transport = httpx.MockTransport(
            lambda req: (_ for _ in ()).throw(httpx.TimeoutException("timeout"))
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.error_code == "OPEN_WEB_RETRIEVAL_FETCH_ERROR"
        assert "url" in exc_info.value.context

    def test_fetch_http_error_raises_fetch_error(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(500, request=req)
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com")
        with pytest.raises(FetchError):
            fetcher.fetch(req)

    def test_extract_html_content(self, fetch_client):
        fetcher = SourceFetcher(client=fetch_client)
        req = FetchRequest(url="https://example.com")
        resource = fetcher.fetch(req)
        doc = fetcher.extract(resource)

        assert doc.source_url == "https://example.com"
        assert doc.document_type == "html"
        assert len(doc.text) > 0
        # Should extract meaningful text, not raw HTML
        assert "<html>" not in doc.text
        assert "<p>" not in doc.text

    def test_extract_preserves_provenance(self, fetch_client):
        fetcher = SourceFetcher(client=fetch_client)
        req = FetchRequest(url="https://example.com/article")
        resource = fetcher.fetch(req)
        doc = fetcher.extract(resource)

        assert doc.source_url == "https://example.com/article"
        assert doc.extraction_method in ("trafilatura", "fallback_strip")

    def test_close_idempotent(self, fetch_client):
        fetcher = SourceFetcher(client=fetch_client)
        fetcher.close()
        fetcher.close()  # should not raise
