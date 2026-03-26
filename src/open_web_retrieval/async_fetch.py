"""Async fetch and extraction primitives mirroring the sync SourceFetcher API."""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

import httpx

from open_web_retrieval import __version__
from open_web_retrieval.exceptions import FetchError
from open_web_retrieval.fetch_extract import (
    KNOWN_BLOCKED_DOMAINS,
    NON_RETRYABLE_STATUS,
    _DEFAULT_RETRY_AFTER_SECONDS,
    _extract_embedded_json,
    _extract_text,
    _hash_bytes,
    _looks_like_js_shell,
    _parse_date_string,
    _parse_retry_after,
    _utc_now,
)
from open_web_retrieval.models import (
    ExtractedDocument,
    FetchMetrics,
    FetchRequest,
    FetchedResource,
)
from open_web_retrieval.observability import (
    ToolCallLogger,
    duration_ms,
    emit_tool_call,
    make_tool_call_id,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class AsyncSourceFetcher:
    """Async counterpart of SourceFetcher — same contract, async/await interface.

    Uses ``httpx.AsyncClient`` for non-blocking HTTP and ``asyncio.sleep``
    for rate-limit waits.  Extraction is CPU-bound and delegates to the
    same shared helpers used by the sync fetcher.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        user_agent_profile: str = f"open_web_retrieval/{__version__}",
        client: httpx.AsyncClient | None = None,
        blocked_domains: set[str] | None = None,
        rate_limit_per_second: float = 2.0,
        tool_call_logger: ToolCallLogger | None = None,
        enable_auto_render: bool = True,
    ) -> None:
        """Construct an async fetcher with injected HTTP transport.

        Args:
            timeout_seconds: Per-request timeout passed to ``httpx.AsyncClient``.
            user_agent_profile: Default User-Agent header value.
            client: Optional pre-built ``httpx.AsyncClient`` (e.g. with
                ``MockTransport`` for testing).  When provided the fetcher
                does **not** own the client and will not close it.
            blocked_domains: Domain names to reject immediately.
            rate_limit_per_second: Max requests/s per domain.  0 disables.
            tool_call_logger: Optional observability logger.
            enable_auto_render: When True, detect JS-rendered SPAs and
                attempt embedded-JSON extraction.  Playwright escalation
                is NOT supported in the async fetcher — use the sync
                fetcher for that.
        """
        self._enable_auto_render = enable_auto_render
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self.user_agent_profile = user_agent_profile
        self._blocked_domains = blocked_domains if blocked_domains is not None else KNOWN_BLOCKED_DOMAINS
        self._rate_limit = rate_limit_per_second
        self._last_request: dict[str, float] = {}  # domain -> monotonic timestamp
        self.metrics = FetchMetrics()
        self.tool_call_logger = tool_call_logger

    async def _rate_limit_wait(self, domain: str) -> None:
        """Async sleep if needed to respect per-domain rate limits."""
        if self._rate_limit <= 0:
            return
        now = time.monotonic()
        if domain in self._last_request:
            min_interval = 1.0 / self._rate_limit
            elapsed = now - self._last_request[domain]
            wait = max(0.0, min_interval - elapsed)
            if wait > 0:
                logger.debug("RATE_LIMIT domain=%s wait=%.2fs", domain, wait)
                await asyncio.sleep(wait)
                self.metrics.total_wait_seconds += wait
        self._last_request[domain] = time.monotonic()

    async def fetch(
        self,
        request: FetchRequest,
        *,
        trace_id: str | None = None,
        task: str | None = None,
    ) -> FetchedResource:
        """Fetch the URL using async HTTP with normalized provenance output.

        Mirrors ``SourceFetcher.fetch`` but uses ``await`` for the HTTP call
        and ``asyncio.sleep`` for 429 back-off.

        Raises:
            FetchError: With ``retryable=False`` for permanent failures
                (4xx auth/not-found, blocked domains) and ``retryable=True``
                for transient failures (timeouts, 5xx, rate limits).
        """
        call_id = make_tool_call_id()
        started_at = utc_now_iso()
        started_monotonic = time.monotonic() if self.tool_call_logger is not None else None

        # Check blocked domains before any network request.
        domain = urlparse(request.url).netloc.removeprefix("www.")
        base_metrics: dict = {
            "domain": domain,
            "render_mode": request.render_mode,
            "max_bytes": request.max_bytes,
        }
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider="httpx_async",
            target=request.url,
            status="started",
            started_at=started_at,
            attempt=1,
            task=task,
            trace_id=trace_id,
            metrics=base_metrics,
        )

        if domain in self._blocked_domains:
            logger.info("SKIP blocked domain=%s url=%s", domain, request.url)
            self.metrics.skipped_blocked += 1
            emit_tool_call(
                self.tool_call_logger,
                call_id=call_id,
                tool_name="open_web_retrieval",
                operation="fetch",
                provider="httpx_async",
                target=request.url,
                status="failed",
                started_at=started_at,
                ended_at=utc_now_iso(),
                duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
                attempt=1,
                task=task,
                trace_id=trace_id,
                metrics={**base_metrics, "retryable": False},
                error_type="FetchError",
                error_message=f"blocked domain: {domain}",
            )
            raise FetchError(
                f"blocked domain: {domain}",
                retryable=False,
                context={"url": request.url, "domain": domain},
            )

        # Per-domain rate limiting.
        await self._rate_limit_wait(domain)

        headers = {"User-Agent": request.user_agent_profile}
        try:
            response = await self.client.get(
                request.url, headers=headers, follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.info("FETCH_TIMEOUT url=%s", request.url)
            self.metrics.failed += 1
            emit_tool_call(
                self.tool_call_logger,
                call_id=call_id,
                tool_name="open_web_retrieval",
                operation="fetch",
                provider="httpx_async",
                target=request.url,
                status="failed",
                started_at=started_at,
                ended_at=utc_now_iso(),
                duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
                attempt=1,
                task=task,
                trace_id=trace_id,
                metrics={**base_metrics, "retryable": True},
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise FetchError(
                "fetch timed out",
                retryable=True,
                context={"url": request.url, "method": "httpx_async"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=call_id,
                    tool_name="open_web_retrieval",
                    operation="fetch",
                    provider="httpx_async",
                    target=request.url,
                    status="failed",
                    started_at=started_at,
                    ended_at=utc_now_iso(),
                    duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
                    attempt=1,
                    task=task,
                    trace_id=trace_id,
                    metrics={**base_metrics, "http_status": 429, "retryable": True},
                    error_type="HTTPStatusError",
                    error_message="HTTP 429",
                )
                # Respect Retry-After header and retry once.
                retry_after_header = exc.response.headers.get("Retry-After")
                wait = (
                    _parse_retry_after(retry_after_header)
                    if retry_after_header
                    else _DEFAULT_RETRY_AFTER_SECONDS
                )
                logger.info(
                    "RATE_LIMITED url=%s retry_after=%.1fs", request.url, wait,
                )
                self.metrics.total_wait_seconds += wait
                await asyncio.sleep(wait)
                self.metrics.retried += 1

                retry_call_id = make_tool_call_id()
                retry_started_at = utc_now_iso()
                retry_started_monotonic = (
                    time.monotonic() if self.tool_call_logger is not None else None
                )
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=retry_call_id,
                    tool_name="open_web_retrieval",
                    operation="fetch",
                    provider="httpx_async",
                    target=request.url,
                    status="started",
                    started_at=retry_started_at,
                    attempt=2,
                    task=task,
                    trace_id=trace_id,
                    metrics={**base_metrics, "retry_after_seconds": wait},
                )
                try:
                    response = await self.client.get(
                        request.url, headers=headers, follow_redirects=True,
                    )
                    response.raise_for_status()
                    emit_tool_call(
                        self.tool_call_logger,
                        call_id=retry_call_id,
                        tool_name="open_web_retrieval",
                        operation="fetch",
                        provider="httpx_async",
                        target=request.url,
                        status="succeeded",
                        started_at=retry_started_at,
                        ended_at=utc_now_iso(),
                        duration_ms_value=(
                            duration_ms(retry_started_monotonic)
                            if retry_started_monotonic is not None
                            else None
                        ),
                        attempt=2,
                        task=task,
                        trace_id=trace_id,
                        metrics={
                            **base_metrics,
                            "http_status": response.status_code,
                            "content_type": response.headers.get("content-type"),
                            "retry_after_seconds": wait,
                        },
                    )
                except (httpx.HTTPError, httpx.TimeoutException) as retry_exc:
                    self.metrics.failed += 1
                    emit_tool_call(
                        self.tool_call_logger,
                        call_id=retry_call_id,
                        tool_name="open_web_retrieval",
                        operation="fetch",
                        provider="httpx_async",
                        target=request.url,
                        status="failed",
                        started_at=retry_started_at,
                        ended_at=utc_now_iso(),
                        duration_ms_value=(
                            duration_ms(retry_started_monotonic)
                            if retry_started_monotonic is not None
                            else None
                        ),
                        attempt=2,
                        task=task,
                        trace_id=trace_id,
                        metrics={
                            **base_metrics,
                            "http_status": 429,
                            "retry_after_seconds": wait,
                            "retryable": True,
                        },
                        error_type=retry_exc.__class__.__name__,
                        error_message=str(retry_exc),
                    )
                    raise FetchError(
                        "HTTP 429 retry failed",
                        retryable=True,
                        context={
                            "url": request.url,
                            "status": 429,
                            "retry_after": wait,
                        },
                    ) from retry_exc
            else:
                retryable = exc.response.status_code not in NON_RETRYABLE_STATUS
                if retryable:
                    logger.info(
                        "FETCH_FAILED_RETRYABLE status=%d url=%s",
                        exc.response.status_code,
                        request.url,
                    )
                    self.metrics.failed += 1
                else:
                    logger.info(
                        "SKIP_PERMANENT status=%d url=%s",
                        exc.response.status_code,
                        request.url,
                    )
                    self.metrics.skipped_permanent += 1
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=call_id,
                    tool_name="open_web_retrieval",
                    operation="fetch",
                    provider="httpx_async",
                    target=request.url,
                    status="failed",
                    started_at=started_at,
                    ended_at=utc_now_iso(),
                    duration_ms_value=(
                        duration_ms(started_monotonic)
                        if started_monotonic is not None
                        else None
                    ),
                    attempt=1,
                    task=task,
                    trace_id=trace_id,
                    metrics={
                        **base_metrics,
                        "http_status": exc.response.status_code,
                        "retryable": retryable,
                    },
                    error_type="HTTPStatusError",
                    error_message=f"HTTP {exc.response.status_code}",
                )
                raise FetchError(
                    f"HTTP {exc.response.status_code}",
                    retryable=retryable,
                    context={
                        "url": request.url,
                        "status": exc.response.status_code,
                    },
                ) from exc
        except httpx.HTTPError as exc:
            self.metrics.failed += 1
            emit_tool_call(
                self.tool_call_logger,
                call_id=call_id,
                tool_name="open_web_retrieval",
                operation="fetch",
                provider="httpx_async",
                target=request.url,
                status="failed",
                started_at=started_at,
                ended_at=utc_now_iso(),
                duration_ms_value=(
                    duration_ms(started_monotonic)
                    if started_monotonic is not None
                    else None
                ),
                attempt=1,
                task=task,
                trace_id=trace_id,
                metrics={**base_metrics, "retryable": True},
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise FetchError(
                "fetch failed",
                retryable=True,
                context={"url": request.url, "method": "httpx_async"},
            ) from exc

        content = response.content
        if len(content) > request.max_bytes:
            content = content[: request.max_bytes]
        self.metrics.fetched += 1
        logger.info(
            "FETCH status=%d url=%s method=httpx_async bytes=%d",
            response.status_code,
            request.url,
            len(content),
        )
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider="httpx_async",
            target=request.url,
            status="succeeded",
            started_at=started_at,
            ended_at=utc_now_iso(),
            duration_ms_value=(
                duration_ms(started_monotonic)
                if started_monotonic is not None
                else None
            ),
            attempt=1,
            task=task,
            trace_id=trace_id,
            metrics={
                **base_metrics,
                "http_status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "byte_count": len(content),
                "final_url": str(response.url),
            },
        )
        return FetchedResource(
            requested_url=request.url,
            final_url=str(response.url),
            status=response.status_code,
            content_type=response.headers.get("content-type"),
            content_bytes=content,
            retrieved_at_utc=_utc_now(),
            fetch_method="httpx_async",
            sha256=_hash_bytes(content),
        )

    def extract(
        self,
        resource: FetchedResource,
        *,
        method: str = "trafilatura",
        trace_id: str | None = None,
        task: str | None = None,
    ) -> ExtractedDocument:
        """Extract normalized text and provenance from fetched bytes.

        Extraction is CPU-bound so this is a regular (sync) method.  It
        reuses the same ``_extract_text`` helper as the sync fetcher.
        """
        call_id = make_tool_call_id()
        started_at = utc_now_iso()
        started_monotonic = time.monotonic() if self.tool_call_logger is not None else None
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="extract",
            provider=method,
            target=resource.requested_url,
            status="started",
            started_at=started_at,
            attempt=1,
            task=task,
            trace_id=trace_id,
            metrics={
                "content_type": resource.content_type,
                "fetch_method": resource.fetch_method,
            },
        )
        text, markdown, metadata, method_used, warnings = _extract_text(
            resource, method=method,
        )
        document = ExtractedDocument(
            source_url=resource.requested_url,
            final_url=resource.final_url,
            title=metadata.get("title"),
            publisher_guess=metadata.get("sitename") or metadata.get("author"),
            published_at_guess=_parse_date_string(metadata.get("date")),
            text=text,
            markdown=markdown,
            document_type=(
                "html"
                if "html" in (resource.content_type or "").lower()
                else "unknown"
            ),
            extraction_method=method_used,
            warnings=warnings,
        )

        # SPA detection: try embedded JSON extraction (no Playwright in async).
        if (
            self._enable_auto_render
            and resource.fetch_method not in ("render_playwright", "crawl4ai")
            and _looks_like_js_shell(resource.content_bytes, document.text)
        ):
            embedded_json = _extract_embedded_json(resource.content_bytes)
            if embedded_json:
                logger.info(
                    "SPA_DETECTED url=%s text_len=%d — extracted embedded JSON (%d chars)",
                    resource.requested_url,
                    len(document.text),
                    len(embedded_json),
                )
                document = ExtractedDocument(
                    source_url=resource.requested_url,
                    final_url=resource.final_url,
                    title=document.title,
                    publisher_guess=document.publisher_guess,
                    published_at_guess=document.published_at_guess,
                    text=embedded_json,
                    markdown="",
                    document_type="html",
                    extraction_method="embedded_json",
                    warnings=document.warnings
                    + ["extracted embedded SSR JSON (no render needed)"],
                )

        logger.debug(
            "EXTRACT url=%s method=%s title=%s markdown_len=%d text_len=%d",
            resource.requested_url,
            method_used,
            document.title,
            len(document.markdown),
            len(document.text),
        )
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="extract",
            provider=method_used,
            target=resource.requested_url,
            status="succeeded",
            started_at=started_at,
            ended_at=utc_now_iso(),
            duration_ms_value=(
                duration_ms(started_monotonic)
                if started_monotonic is not None
                else None
            ),
            attempt=1,
            task=task,
            trace_id=trace_id,
            metrics={
                "document_type": document.document_type,
                "text_chars": len(document.text),
                "markdown_chars": len(document.markdown),
                "warning_count": len(document.warnings),
            },
        )
        return document

    async def close(self) -> None:
        """Release the async HTTP client if we own it."""
        if getattr(self, "_owns_client", False):
            await self.client.aclose()

    async def __aenter__(self):
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context manager — release resources."""
        await self.close()
        return False
