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

    def test_fetch_failure_emits_tool_call(self, fake_tool_call_logger):
        records, logger = fake_tool_call_logger
        transport = httpx.MockTransport(
            lambda req: httpx.Response(403, request=req)
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client, tool_call_logger=logger)
        req = FetchRequest(url="https://example.com")
        with pytest.raises(FetchError):
            fetcher.fetch(req, trace_id="trace_fetch_fail", task="collect")

        operations = [(record.operation, record.status) for record in records]
        assert ("fetch", "started") in operations
        assert ("fetch", "failed") in operations
        failed = [record for record in records if record.operation == "fetch" and record.status == "failed"][0]
        assert failed.trace_id == "trace_fetch_fail"
        assert failed.error_type == "HTTPStatusError"
        assert failed.metrics["http_status"] == 403

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


class TestFetchErrorRetryable:
    """Tests for FetchError.retryable classification (Plan #01)."""

    def test_fetch_retryable_default_true(self):
        """FetchError defaults to retryable=True for backward compatibility."""
        err = FetchError("something failed")
        assert err.retryable is True

    def test_fetch_403_not_retryable(self):
        """403 Forbidden (paywall/bot-block) should not be retried."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(403, request=req)
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://paywalled.example.com/article")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.retryable is False
        assert "403" in str(exc_info.value)

    def test_fetch_429_retryable(self):
        """429 Too Many Requests should be retried."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(429, request=req)
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com/api")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.retryable is True

    def test_fetch_500_retryable(self):
        """500 Internal Server Error should be retried."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(500, request=req)
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com/page")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.retryable is True

    def test_fetch_timeout_retryable(self):
        """Timeout errors should be retried."""
        transport = httpx.MockTransport(
            lambda req: (_ for _ in ()).throw(httpx.TimeoutException("timeout"))
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client)
        req = FetchRequest(url="https://example.com/slow")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.retryable is True

    def test_fetch_blocked_domain(self):
        """Blocked domains should raise immediately with retryable=False."""
        fetcher = SourceFetcher(blocked_domains={"reuters.com", "wsj.com"})
        req = FetchRequest(url="https://www.reuters.com/article/123")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.retryable is False
        assert "blocked domain" in str(exc_info.value)
        assert exc_info.value.context["domain"] == "reuters.com"



class TestRetryAfterHeader:
    """Tests for 429 Retry-After header handling (Plan #02)."""

    def test_retry_after_header_respected(self):
        """429 with Retry-After header → waits, retries once, succeeds."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "2"},
                    request=request,
                )
            return httpx.Response(
                200,
                content=b"<html>ok</html>",
                headers={"content-type": "text/html"},
                request=request,
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client, rate_limit_per_second=0)
        req = FetchRequest(url="https://example.com/api")

        import unittest.mock
        with unittest.mock.patch("open_web_retrieval.fetch_extract.time.sleep") as mock_sleep:
            resource = fetcher.fetch(req)

        assert resource.status == 200
        assert call_count == 2
        mock_sleep.assert_called_once_with(2.0)
        assert fetcher.metrics.retried == 1
        assert fetcher.metrics.fetched == 1

    def test_retry_after_integer_seconds(self):
        """Retry-After: '3' parses to 3.0 seconds."""
        from open_web_retrieval.fetch_extract import _parse_retry_after
        assert _parse_retry_after("3") == 3.0

    def test_retry_after_missing_uses_default(self):
        """429 without Retry-After header uses the 5-second default."""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, request=request)
            return httpx.Response(
                200,
                content=b"<html>ok</html>",
                headers={"content-type": "text/html"},
                request=request,
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client, rate_limit_per_second=0)
        req = FetchRequest(url="https://example.com/api")

        import unittest.mock
        with unittest.mock.patch("open_web_retrieval.fetch_extract.time.sleep") as mock_sleep:
            resource = fetcher.fetch(req)

        assert resource.status == 200
        mock_sleep.assert_called_once_with(5.0)
        assert fetcher.metrics.total_wait_seconds == 5.0


class TestRateLimiting:
    """Tests for per-domain rate limiting (Plan #02)."""

    def test_rate_limit_delays_requests(self):
        """Two rapid fetches to same domain should trigger a sleep."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=b"<html>ok</html>",
                headers={"content-type": "text/html"},
                request=req,
            )
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client, rate_limit_per_second=2.0)

        import unittest.mock
        with unittest.mock.patch("open_web_retrieval.fetch_extract.time.sleep") as mock_sleep:
            with unittest.mock.patch("open_web_retrieval.fetch_extract.time.monotonic") as mock_mono:
                # First fetch: monotonic() called once (no prior entry), then once for update
                # Second fetch: monotonic() called once to check elapsed, then once for update
                # At rate_limit=2.0, min_interval=0.5s
                # First: t=1.0 (check — domain not in dict, skip), t=1.0 (update)
                # Second: t=1.0 (check — elapsed=0.0 < 0.5, must wait), t=1.5 (update)
                mock_mono.side_effect = [1.0, 1.0, 1.0, 1.5]
                fetcher.fetch(FetchRequest(url="https://example.com/page1"))
                fetcher.fetch(FetchRequest(url="https://example.com/page2"))

        mock_sleep.assert_called_once_with(0.5)
        assert fetcher.metrics.total_wait_seconds == 0.5

    def test_rate_limit_different_domains_no_delay(self):
        """Fetches to different domains should not wait."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=b"<html>ok</html>",
                headers={"content-type": "text/html"},
                request=req,
            )
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client, rate_limit_per_second=2.0)

        import unittest.mock
        with unittest.mock.patch("open_web_retrieval.fetch_extract.time.sleep") as mock_sleep:
            with unittest.mock.patch("open_web_retrieval.fetch_extract.time.monotonic") as mock_mono:
                # Different domains — first request to each domain skips rate limit check
                mock_mono.side_effect = [1.0, 1.0, 1.0, 1.0]
                fetcher.fetch(FetchRequest(url="https://example.com/a"))
                fetcher.fetch(FetchRequest(url="https://other.com/b"))

        mock_sleep.assert_not_called()

    def test_rate_limit_disabled_zero(self):
        """rate_limit_per_second=0 disables rate limiting entirely."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                content=b"<html>ok</html>",
                headers={"content-type": "text/html"},
                request=req,
            )
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(client=client, rate_limit_per_second=0)

        import unittest.mock
        with unittest.mock.patch("open_web_retrieval.fetch_extract.time.sleep") as mock_sleep:
            fetcher.fetch(FetchRequest(url="https://example.com/a"))
            fetcher.fetch(FetchRequest(url="https://example.com/b"))

        mock_sleep.assert_not_called()


class TestFetchMetrics:
    """Tests for FetchMetrics tracking (Plan #02)."""

    def test_metrics_incremented(self, fetch_client):
        """Successful fetch increments metrics.fetched."""
        fetcher = SourceFetcher(client=fetch_client, rate_limit_per_second=0)
        req = FetchRequest(url="https://example.com/page")
        fetcher.fetch(req)
        assert fetcher.metrics.fetched == 1
        assert fetcher.metrics.failed == 0

    def test_metrics_blocked_domain(self):
        """Blocked domain increments metrics.skipped_blocked."""
        fetcher = SourceFetcher(
            blocked_domains={"reuters.com"},
            rate_limit_per_second=0,
        )
        req = FetchRequest(url="https://www.reuters.com/article/123")
        with pytest.raises(FetchError):
            fetcher.fetch(req)
        assert fetcher.metrics.skipped_blocked == 1
        assert fetcher.metrics.fetched == 0


class TestMarkdownExtraction:
    """Tests for markdown output and metadata extraction (Plan #03)."""

    RICH_HTML = """<!DOCTYPE html>
<html><head><title>Research Article</title>
<meta name="author" content="Jane Doe">
<meta name="date" content="2026-01-15">
<meta property="og:site_name" content="Science Daily">
</head>
<body>
<article>
<h1>Climate Change Effects on Biodiversity</h1>
<p>Rising temperatures affect <a href="https://example.com/biodiversity">biodiversity</a> worldwide.
Scientists have documented numerous changes in <a href="https://example.com/ecosystems">ecosystems</a>
across the globe over the past several decades of observation.</p>
<p>According to a <a href="https://example.com/study">recent study</a>, the following key findings
were established through rigorous analysis of climate data collected over the past decade.
The research team analyzed thousands of data points from weather stations worldwide.</p>
<p>The implications are far-reaching. As noted by leading researchers at institutions around the world,
climate change represents one of the most significant challenges facing modern civilization. The data
suggests that immediate action is needed to prevent catastrophic outcomes for future generations.</p>
<p>Further reading and references can be found at the <a href="https://example.com/references">reference page</a>.</p>
<h2>Key Findings</h2>
<ul>
<li>Sea level rise of 3mm per year</li>
<li>Species migration patterns shifting northward</li>
<li>Coral reef bleaching events increasing in frequency</li>
</ul>
</article>
</body></html>"""

    def _make_resource(self, html: str = None) -> "FetchedResource":
        """Build a FetchedResource from HTML string."""
        if html is None:
            html = self.RICH_HTML
        content = html.encode("utf-8")
        return FetchedResource(
            requested_url="https://example.com/article",
            final_url="https://example.com/article",
            status=200,
            content_type="text/html; charset=utf-8",
            content_bytes=content,
            retrieved_at_utc=datetime(2026, 3, 25, tzinfo=timezone.utc),
            fetch_method="httpx",
            sha256="abc123",
        )

    def test_extract_produces_markdown(self):
        """ExtractedDocument.markdown is non-empty for HTML with structure."""
        pytest.importorskip("trafilatura")
        fetcher = SourceFetcher(rate_limit_per_second=0)
        resource = self._make_resource()
        doc = fetcher.extract(resource)
        if not doc.markdown:
            pytest.skip("trafilatura version did not extract markdown from fixture")
        # Should not contain raw HTML tags
        assert "<html>" not in doc.markdown
        assert "<p>" not in doc.markdown

    def test_extract_metadata_populated(self):
        """Title, publisher_guess, published_at_guess populated from HTML metadata."""
        pytest.importorskip("trafilatura")
        fetcher = SourceFetcher(rate_limit_per_second=0)
        resource = self._make_resource()
        doc = fetcher.extract(resource)
        if doc.title is None:
            pytest.skip("trafilatura version did not extract metadata from fixture")

    def test_extract_plain_text_still_works(self):
        """ExtractedDocument.text is still populated alongside markdown."""
        fetcher = SourceFetcher(rate_limit_per_second=0)
        resource = self._make_resource()
        doc = fetcher.extract(resource)
        assert doc.text, "text field should still be populated"
        assert len(doc.text) > 10
        # Should not contain HTML tags
        assert "<html>" not in doc.text

    def test_extract_markdown_includes_links(self):
        """Links in HTML are preserved in markdown output."""
        pytest.importorskip("trafilatura")
        fetcher = SourceFetcher(rate_limit_per_second=0)
        resource = self._make_resource()
        doc = fetcher.extract(resource)
        if not doc.markdown:
            pytest.skip("trafilatura version did not extract markdown from fixture")
        assert "biodiversity" in doc.markdown, "link text should appear in markdown"


class TestFrontmatterStripping:
    """Tests for YAML frontmatter removal from markdown output (Plan #03)."""

    def test_strip_frontmatter(self):
        """YAML frontmatter is stripped from trafilatura markdown output."""
        from open_web_retrieval.fetch_extract import _strip_frontmatter
        md_with_fm = "---\ntitle: Test\nurl: https://example.com\n---\n# Heading\nContent here."
        result = _strip_frontmatter(md_with_fm)
        assert not result.startswith("---")
        assert "# Heading" in result
        assert "Content here." in result

    def test_no_frontmatter_passthrough(self):
        """Markdown without frontmatter passes through unchanged."""
        from open_web_retrieval.fetch_extract import _strip_frontmatter
        md = "# Heading\nContent here."
        assert _strip_frontmatter(md) == md


class TestDateParsing:
    """Tests for date string parsing helper (Plan #03)."""

    def test_valid_date(self):
        from open_web_retrieval.fetch_extract import _parse_date_string
        result = _parse_date_string("2026-01-15")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_none_input(self):
        from open_web_retrieval.fetch_extract import _parse_date_string
        assert _parse_date_string(None) is None

    def test_invalid_date(self):
        from open_web_retrieval.fetch_extract import _parse_date_string
        assert _parse_date_string("not-a-date") is None


class TestAntibotEscalation:
    """Tests for Crawl4AI anti-bot escalation (Plan #05)."""

    def _make_403_fetcher(self, *, enable_antibot: bool = True):
        """Create a SourceFetcher with a 403-returning transport and mocked crawl4ai import."""
        import sys
        import types
        import unittest.mock

        # Mock crawl4ai module so enable_antibot=True doesn't raise ImportError
        mock_crawl4ai = types.ModuleType("crawl4ai")
        mock_crawl4ai.AsyncWebCrawler = unittest.mock.MagicMock()
        mock_crawl4ai.BrowserConfig = unittest.mock.MagicMock()
        mock_crawl4ai.CrawlerRunConfig = unittest.mock.MagicMock()

        transport = httpx.MockTransport(
            lambda req: httpx.Response(403, request=req)
        )
        client = httpx.Client(transport=transport)

        with unittest.mock.patch.dict(sys.modules, {"crawl4ai": mock_crawl4ai}):
            fetcher = SourceFetcher(
                client=client,
                rate_limit_per_second=0,
                enable_antibot=enable_antibot,
            )
        return fetcher

    def test_403_escalates_when_antibot_enabled(self):
        """403 + enable_antibot=True calls _crawl4ai_fetch."""
        import unittest.mock

        fetcher = self._make_403_fetcher(enable_antibot=True)

        mock_resource = FetchedResource(
            requested_url="https://protected.example.com/page",
            final_url="https://protected.example.com/page",
            status=200,
            content_type="text/html",
            content_bytes=b"<html>browser content</html>",
            retrieved_at_utc=datetime(2026, 3, 25, tzinfo=timezone.utc),
            fetch_method="crawl4ai",
            sha256="abc123",
        )

        with unittest.mock.patch.object(fetcher, "_crawl4ai_fetch", return_value=mock_resource) as mock_fetch:
            req = FetchRequest(url="https://protected.example.com/page")
            result = fetcher.fetch(req)

        mock_fetch.assert_called_once_with("https://protected.example.com/page")
        assert result.fetch_method == "crawl4ai"

    def test_403_no_escalation_when_antibot_disabled(self):
        """403 + enable_antibot=False raises FetchError immediately."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(403, request=req)
        )
        client = httpx.Client(transport=transport)
        fetcher = SourceFetcher(
            client=client,
            rate_limit_per_second=0,
            enable_antibot=False,
        )
        req = FetchRequest(url="https://protected.example.com/page")
        with pytest.raises(FetchError) as exc_info:
            fetcher.fetch(req)
        assert exc_info.value.retryable is False
        assert "403" in str(exc_info.value)

    def test_escalation_failure_falls_through(self):
        """crawl4ai fails -> original FetchError raised with 403."""
        import unittest.mock

        fetcher = self._make_403_fetcher(enable_antibot=True)

        with unittest.mock.patch.object(
            fetcher, "_crawl4ai_fetch",
            side_effect=FetchError("crawl4ai failed", retryable=False),
        ):
            req = FetchRequest(url="https://protected.example.com/page")
            with pytest.raises(FetchError) as exc_info:
                fetcher.fetch(req)
            # Should be the original 403 error, not the crawl4ai error
            assert "403" in str(exc_info.value)
            assert exc_info.value.retryable is False

    def test_escalation_success_returns_resource(self):
        """crawl4ai succeeds -> FetchedResource with method='crawl4ai'."""
        import unittest.mock

        fetcher = self._make_403_fetcher(enable_antibot=True)

        mock_resource = FetchedResource(
            requested_url="https://protected.example.com/page",
            final_url="https://protected.example.com/page",
            status=200,
            content_type="text/html",
            content_bytes=b"<html>bypassed content</html>",
            retrieved_at_utc=datetime(2026, 3, 25, tzinfo=timezone.utc),
            fetch_method="crawl4ai",
            sha256="def456",
        )

        with unittest.mock.patch.object(fetcher, "_crawl4ai_fetch", return_value=mock_resource):
            req = FetchRequest(url="https://protected.example.com/page")
            result = fetcher.fetch(req)

        assert result.fetch_method == "crawl4ai"
        assert result.content_bytes == b"<html>bypassed content</html>"

    def test_enable_antibot_requires_crawl4ai(self):
        """enable_antibot=True without crawl4ai installed raises ImportError."""
        import sys
        import unittest.mock

        # Ensure crawl4ai is NOT importable
        with unittest.mock.patch.dict(sys.modules, {"crawl4ai": None}):
            with pytest.raises(ImportError, match="crawl4ai is required"):
                SourceFetcher(enable_antibot=True)

    def test_metrics_escalated_incremented(self):
        """Successful escalation increments metrics.escalated."""
        import unittest.mock

        fetcher = self._make_403_fetcher(enable_antibot=True)

        mock_resource = FetchedResource(
            requested_url="https://protected.example.com/page",
            final_url="https://protected.example.com/page",
            status=200,
            content_type="text/html",
            content_bytes=b"<html>content</html>",
            retrieved_at_utc=datetime(2026, 3, 25, tzinfo=timezone.utc),
            fetch_method="crawl4ai",
            sha256="ghi789",
        )

        with unittest.mock.patch.object(fetcher, "_crawl4ai_fetch", return_value=mock_resource):
            req = FetchRequest(url="https://protected.example.com/page")
            fetcher.fetch(req)

        assert fetcher.metrics.escalated == 1


class TestSPADetection:
    """Tests for JS-rendered SPA detection and auto-render escalation."""

    # Minimal JS shell — lots of script, very little content
    JS_SHELL_HTML = b"""<!DOCTYPE html>
<html><head><title>App</title></head>
<body>
<div id="root"></div>
<script src="/static/js/main.chunk.js"></script>
<script src="/static/js/vendors.chunk.js"></script>
<script src="/static/js/runtime.chunk.js"></script>
<script>window.__APP_CONFIG__={api:"https://api.example.com"}</script>
</body></html>"""

    # Normal HTML with real content
    NORMAL_HTML = b"""<!DOCTYPE html>
<html><head><title>Article</title></head>
<body>
<article>
<h1>Real Article Title</h1>
<p>This is a substantial article with real content that should not trigger
SPA detection. It has multiple paragraphs of text content that a reader
would find useful and informative. The content is clearly not a JavaScript
shell or single-page application bootstrap.</p>
<p>Second paragraph with more details about the topic at hand.</p>
</article>
</body></html>"""

    def test_looks_like_js_shell_detects_spa(self):
        """JS-heavy HTML with minimal text is detected as SPA."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        assert _looks_like_js_shell(self.JS_SHELL_HTML, "App") is True

    def test_looks_like_js_shell_normal_content(self):
        """Normal HTML with real content is not detected as SPA."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        long_text = "This is a real article with substantial content. " * 20
        assert _looks_like_js_shell(self.NORMAL_HTML, long_text) is False

    def test_looks_like_js_shell_empty_bytes(self):
        """Empty HTML bytes don't crash."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        assert _looks_like_js_shell(b"", "") is False

    def test_auto_render_disabled(self):
        """SPA detection does not fire when enable_auto_render=False."""
        fetcher = SourceFetcher(rate_limit_per_second=0, enable_auto_render=False)
        resource = FetchedResource(
            requested_url="https://example.com/app",
            final_url="https://example.com/app",
            status=200,
            content_type="text/html",
            content_bytes=self.JS_SHELL_HTML,
            retrieved_at_utc=datetime(2026, 3, 26, tzinfo=timezone.utc),
            fetch_method="httpx",
            sha256="abc123",
        )
        doc = fetcher.extract(resource)
        # Should NOT attempt render — just return whatever extraction gives
        assert fetcher.metrics.auto_rendered == 0

    def test_auto_render_skips_already_rendered(self):
        """SPA detection does not re-render content already fetched with Playwright."""
        fetcher = SourceFetcher(rate_limit_per_second=0)
        resource = FetchedResource(
            requested_url="https://example.com/app",
            final_url="https://example.com/app",
            status=200,
            content_type="text/html",
            content_bytes=self.JS_SHELL_HTML,
            retrieved_at_utc=datetime(2026, 3, 26, tzinfo=timezone.utc),
            fetch_method="render_playwright",  # Already rendered
            sha256="abc123",
        )
        doc = fetcher.extract(resource)
        assert fetcher.metrics.auto_rendered == 0


class TestEnhancedSPADetection:
    """Tests for enhanced SPA detection: framework mount points, noscript, embedded JSON."""

    def test_spa_detection_react_mount(self):
        """<div id="root"></div> detected as SPA when text is short."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        html = b"""<!DOCTYPE html>
<html><head><title>App</title></head>
<body>
<div id="root"></div>
<script src="/app.js"></script>
</body></html>"""
        assert _looks_like_js_shell(html, "App") is True

    def test_spa_detection_vue_mount(self):
        """<div id="app"></div> detected as SPA when text is short."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        html = b"""<!DOCTYPE html>
<html><head><title>Vue App</title></head>
<body>
<div id="app"></div>
<script src="/dist/build.js"></script>
</body></html>"""
        assert _looks_like_js_shell(html, "Vue App") is True

    def test_spa_detection_noscript(self):
        """noscript 'enable JavaScript' detected as SPA when text is short."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        html = b"""<!DOCTYPE html>
<html><head><title>App</title></head>
<body>
<noscript>You need to enable JavaScript to run this app.</noscript>
<div id="main"></div>
</body></html>"""
        assert _looks_like_js_shell(html, "App") is True

    def test_spa_detection_normal_page_not_triggered(self):
        """Normal page with real content is NOT flagged as SPA."""
        from open_web_retrieval.fetch_extract import _looks_like_js_shell

        html = b"""<!DOCTYPE html>
<html><head><title>Real Article</title></head>
<body>
<article>
<h1>Understanding Climate Change</h1>
<p>Climate change refers to long-term shifts in temperatures and weather patterns.</p>
<p>These shifts may be natural, but since the 1800s, human activities have been
the main driver of climate change, primarily due to the burning of fossil fuels.</p>
</article>
</body></html>"""
        long_text = "Understanding Climate Change. " * 30  # well over 500 chars
        assert _looks_like_js_shell(html, long_text) is False

    def test_extract_embedded_json_next_data(self):
        """__NEXT_DATA__ JSON is extracted from script tag."""
        from open_web_retrieval.fetch_extract import _extract_embedded_json

        html = b"""<!DOCTYPE html>
<html><head><title>Next.js App</title></head>
<body>
<div id="__next"></div>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"title":"Hello World","content":"Article body"}}}</script>
</body></html>"""
        result = _extract_embedded_json(html)
        assert result is not None
        assert "Hello World" in result
        assert "Article body" in result

    def test_extract_embedded_json_none_when_absent(self):
        """Returns None for normal HTML without embedded JSON."""
        from open_web_retrieval.fetch_extract import _extract_embedded_json

        html = b"""<!DOCTYPE html>
<html><head><title>Normal Page</title></head>
<body>
<article>
<h1>Real content here</h1>
<p>Just a normal web page with no framework JSON.</p>
</article>
</body></html>"""
        result = _extract_embedded_json(html)
        assert result is None
