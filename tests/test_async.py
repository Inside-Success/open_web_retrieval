"""Contract tests for async fetch and extraction pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import httpx

from open_web_retrieval.async_fetch import AsyncSourceFetcher
from open_web_retrieval.exceptions import FetchError
from open_web_retrieval.models import FetchRequest, FetchedResource


@pytest.mark.asyncio
async def test_async_fetch_success():
    """Async fetcher returns FetchedResource on 200."""

    async def handler(request):
        return httpx.Response(
            200,
            text="<html><body>Hello</body></html>",
            headers={"content-type": "text/html"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=0)
    async with fetcher:
        result = await fetcher.fetch(FetchRequest(url="https://example.com"))
        assert result.status == 200
        assert result.fetch_method == "httpx_async"
        assert b"Hello" in result.content_bytes


@pytest.mark.asyncio
async def test_async_fetch_403_not_retryable():
    """Async fetcher classifies 403 as non-retryable."""

    async def handler(request):
        return httpx.Response(403)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=0)
    async with fetcher:
        with pytest.raises(FetchError) as exc_info:
            await fetcher.fetch(FetchRequest(url="https://example.com"))
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_async_fetch_500_retryable():
    """Async fetcher classifies 500 as retryable."""

    async def handler(request):
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=0)
    async with fetcher:
        with pytest.raises(FetchError) as exc_info:
            await fetcher.fetch(FetchRequest(url="https://example.com"))
        assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_async_fetch_blocked_domain():
    """Async fetcher skips blocked domains."""
    fetcher = AsyncSourceFetcher(
        blocked_domains={"example.com"}, rate_limit_per_second=0,
    )
    async with fetcher:
        with pytest.raises(FetchError) as exc_info:
            await fetcher.fetch(FetchRequest(url="https://example.com"))
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_async_fetch_known_blocked_domain():
    """Async fetcher skips known blocked domains (e.g. reuters.com)."""
    fetcher = AsyncSourceFetcher(rate_limit_per_second=0)
    async with fetcher:
        with pytest.raises(FetchError) as exc_info:
            await fetcher.fetch(FetchRequest(url="https://reuters.com/article/1"))
        assert exc_info.value.retryable is False
        assert "blocked domain" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_context_manager():
    """AsyncSourceFetcher works as async context manager."""
    async with AsyncSourceFetcher(rate_limit_per_second=0) as fetcher:
        assert fetcher is not None


@pytest.mark.asyncio
async def test_async_rate_limiting():
    """Async fetcher respects rate limits with asyncio.sleep."""
    responses = iter([
        httpx.Response(
            200, text="<html>A</html>", headers={"content-type": "text/html"},
        ),
        httpx.Response(
            200, text="<html>B</html>", headers={"content-type": "text/html"},
        ),
    ])

    async def handler(request):
        return next(responses)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=100)
    async with fetcher:
        r1 = await fetcher.fetch(FetchRequest(url="https://a.com/1"))
        r2 = await fetcher.fetch(FetchRequest(url="https://a.com/2"))
        assert r1.status == 200
        assert r2.status == 200


@pytest.mark.asyncio
async def test_async_extract():
    """Async fetcher extract() returns ExtractedDocument from HTML."""

    async def handler(request):
        return httpx.Response(
            200,
            text="<html><body><p>Hello world</p></body></html>",
            headers={"content-type": "text/html"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=0)
    async with fetcher:
        resource = await fetcher.fetch(FetchRequest(url="https://example.com"))
        doc = fetcher.extract(resource)
        assert doc.source_url == "https://example.com"
        assert doc.document_type == "html"
        assert len(doc.text) > 0


@pytest.mark.asyncio
async def test_async_fetch_metrics_updated():
    """Async fetcher updates metrics on successful fetch."""

    async def handler(request):
        return httpx.Response(
            200, text="<html>OK</html>", headers={"content-type": "text/html"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=0)
    async with fetcher:
        assert fetcher.metrics.fetched == 0
        await fetcher.fetch(FetchRequest(url="https://example.com"))
        assert fetcher.metrics.fetched == 1


@pytest.mark.asyncio
async def test_async_fetch_metrics_blocked():
    """Async fetcher increments skipped_blocked on blocked domain."""
    fetcher = AsyncSourceFetcher(
        blocked_domains={"blocked.com"}, rate_limit_per_second=0,
    )
    async with fetcher:
        assert fetcher.metrics.skipped_blocked == 0
        with pytest.raises(FetchError):
            await fetcher.fetch(FetchRequest(url="https://blocked.com/page"))
        assert fetcher.metrics.skipped_blocked == 1


@pytest.mark.asyncio
async def test_async_fetch_content_truncation():
    """Async fetcher truncates content that exceeds max_bytes."""
    big_body = "x" * 10_000

    async def handler(request):
        return httpx.Response(
            200, text=big_body, headers={"content-type": "text/plain"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(client=client, rate_limit_per_second=0)
    async with fetcher:
        result = await fetcher.fetch(
            FetchRequest(url="https://example.com", max_bytes=1000),
        )
        assert len(result.content_bytes) <= 1000


@pytest.mark.asyncio
async def test_async_fetch_emits_trace_and_task(fake_tool_call_logger):
    """Async fetch should preserve trace/task in shared tool-call rows."""

    records, logger = fake_tool_call_logger

    async def handler(request):
        return httpx.Response(
            200,
            text="<html><body>Hello</body></html>",
            headers={"content-type": "text/html"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = AsyncSourceFetcher(
        client=client,
        rate_limit_per_second=0,
        tool_call_logger=logger,
    )
    async with fetcher:
        await fetcher.fetch(
            FetchRequest(url="https://example.com"),
            trace_id="trace_async_fetch",
            task="collect",
        )

    fetch_records = [record for record in records if record.operation == "fetch"]
    assert fetch_records
    assert all(record.trace_id == "trace_async_fetch" for record in fetch_records)
    assert all(record.task == "collect" for record in fetch_records)


@pytest.mark.asyncio
async def test_async_extract_emits_trace_and_task(fake_tool_call_logger):
    """Async extract should preserve trace/task in shared tool-call rows."""

    records, logger = fake_tool_call_logger
    resource = FetchedResource(
        requested_url="https://example.com/page",
        final_url="https://example.com/page",
        status=200,
        content_type="text/html",
        content_bytes=b"<html><body><p>Hello world</p></body></html>",
        retrieved_at_utc=datetime(2026, 3, 26, tzinfo=timezone.utc),
        fetch_method="httpx_async",
        sha256="abc123",
    )

    async with AsyncSourceFetcher(rate_limit_per_second=0, tool_call_logger=logger) as fetcher:
        fetcher.extract(resource, trace_id="trace_async_extract", task="collect")

    extract_records = [record for record in records if record.operation == "extract"]
    assert extract_records
    assert all(record.trace_id == "trace_async_extract" for record in extract_records)
    assert all(record.task == "collect" for record in extract_records)
    assert extract_records[-1].metrics["domain"] == "example.com"
    assert extract_records[-1].metrics["source_fetch_method"] == "httpx_async"
    assert extract_records[-1].metrics["fallback_path"] == "primary"
