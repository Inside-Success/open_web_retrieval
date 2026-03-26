"""Fetch and extraction primitives for retrieved web resources."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime as _datetime
from datetime import timezone as _timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import httpx

from open_web_retrieval.exceptions import FetchError, OpenWebRetrievalError, RenderError
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

# HTTP status codes that indicate permanent failures — retrying won't help.
NON_RETRYABLE_STATUS = {401, 403, 404, 410, 451}

# Domains known to block automated fetching. Skip immediately rather than
# burning 3 retries × backoff (~30s) per URL. Consumers can override via
# SourceFetcher(blocked_domains=...).
KNOWN_BLOCKED_DOMAINS: set[str] = {
    "reuters.com",
    "thehill.com",
    "visualcapitalist.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "nytimes.com",
    "washingtonpost.com",
    "economist.com",
    "foreignaffairs.com",
}

# Default wait when a 429 response lacks a Retry-After header.
_DEFAULT_RETRY_AFTER_SECONDS = 5.0


def _hash_bytes(payload: bytes) -> str:
    """Return SHA-256 checksum for raw fetched bytes."""
    digest = sha256()
    digest.update(payload)
    return digest.hexdigest()


def _decode_text(payload: bytes) -> str:
    """Decode bytes using tolerant UTF-8 fallback to preserve content."""
    return payload.decode("utf-8", errors="replace")


def _strip_html_tags(html_text: str) -> str:
    """Fallback HTML cleanup when extraction libraries are unavailable."""
    output = []
    inside = False
    for char in html_text:
        if char == "<":
            inside = True
            continue
        if char == ">":
            inside = False
            continue
        if not inside:
            output.append(char)
    text = "".join(output)
    text = " ".join(text.split())
    return text.strip()


def _parse_retry_after(header_value: str) -> float:
    """Parse a Retry-After header value into seconds to wait.

    Handles two formats per RFC 7231:
    - Integer seconds (e.g. "3")
    - HTTP-date (e.g. "Sun, 06 Nov 1994 08:49:37 GMT")

    Returns seconds to wait. Falls back to the default if parsing fails.
    """
    # Try integer seconds first.
    try:
        seconds = float(header_value)
        return max(0.0, seconds)
    except ValueError:
        pass

    # Try HTTP-date format.
    try:
        retry_at = parsedate_to_datetime(header_value)
        now = _datetime.now(tz=_timezone.utc)
        delta = (retry_at - now).total_seconds()
        return max(0.0, delta)
    except (ValueError, TypeError):
        pass

    logger.warning("unparseable Retry-After header: %s; using default", header_value)
    return _DEFAULT_RETRY_AFTER_SECONDS


def _strip_frontmatter(md: str) -> str:
    """Remove YAML frontmatter (---\n...\n---) that trafilatura adds to markdown output."""
    if md.startswith("---"):
        end = md.find("---", 3)
        if end != -1:
            stripped = md[end + 3:].lstrip("\n")
            return stripped
    return md


def _parse_date_string(date_str: str | None) -> _datetime | None:
    """Parse a date string (e.g. '2026-01-15') into a datetime, or None on failure."""
    if not date_str:
        return None
    try:
        return _datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_timezone.utc)
    except (ValueError, TypeError):
        return None


def _extract_with_trafilatura(html_text: str, url: str | None = None) -> tuple[str, str, dict]:
    """Extract text, markdown, and metadata from HTML via trafilatura.

    Returns (plain_text, markdown, metadata_dict). On failure or missing
    trafilatura, returns ("", "", {}).

    Uses bare_extraction() for text + metadata (1 call) and extract() for
    markdown (1 call) — 2 parses instead of 3.
    """
    try:
        from trafilatura import bare_extraction, extract
    except ModuleNotFoundError:
        return ("", "", {})

    try:
        # Call 1: bare_extraction for text + metadata (single parse)
        doc = bare_extraction(html_text, url=url, with_metadata=True, favor_recall=True)

        txt = ""
        metadata: dict = {}
        if doc:
            txt = doc.text or ""
            metadata = {
                "title": doc.title,
                "author": doc.author,
                "date": doc.date,
                "sitename": doc.sitename,
            }

        # Call 2: extract for markdown (separate parse — different output format)
        md = extract(html_text, output_format="markdown", include_links=True,
                     include_tables=True, url=url, favor_recall=True)

        return (txt, _strip_frontmatter(md) if md else "", metadata)
    except Exception as exc:
        logger.warning("trafilatura extraction failed: %s", exc)
        return ("", "", {})


# Minimum text length and script-tag ratio that suggests a JS-rendered SPA
_SPA_MIN_TEXT_LEN = 500
_SPA_SCRIPT_RATIO = 0.3  # >30% of HTML is <script> tags

# SPA framework mount-point IDs — empty divs with these IDs are strong SPA signals.
_SPA_MOUNT_IDS = (b"root", b"app", b"__next", b"__nuxt")

# Regex for __NEXT_DATA__ JSON extraction
_NEXT_DATA_RE = re.compile(
    rb"""<script\s+id=["']__NEXT_DATA__["']\s+type=["']application/json["']\s*>(.*?)</script>""",
    re.DOTALL | re.IGNORECASE,
)

# Regex for __NUXT__ JSON extraction
_NUXT_DATA_RE = re.compile(
    rb'window\.__NUXT__\s*=\s*({.*?})\s*;?\s*</script>',
    re.DOTALL,
)

# Noscript patterns that indicate JS-required pages
_NOSCRIPT_JS_REQUIRED = re.compile(
    rb'<noscript[^>]*>.*?(?:enable\s+javascript|javascript\s+is\s+required|javascript\s+must\s+be\s+enabled).*?</noscript>',
    re.DOTALL | re.IGNORECASE,
)


def _has_empty_mount_point(html_lower: bytes) -> bool:
    """Detect common SPA framework mount points (empty or whitespace-only divs).

    Checks for React (<div id="root">), Vue (<div id="app">),
    Next.js (<div id="__next">), and Nuxt (<div id="__nuxt">).
    Returns True if any are found with empty or near-empty content.
    """
    for mount_id in _SPA_MOUNT_IDS:
        # Match <div id="root"></div> or <div id="root"> </div>
        # Use string search instead of regex for reliability
        for quote in (b'"', b"'"):
            tag_open = b'<div' + b' id=' + quote + mount_id + quote
            if tag_open not in html_lower:
                continue
            # Found the opening tag — check if div is empty
            start = html_lower.find(tag_open)
            # Find the closing > of the opening tag
            gt = html_lower.find(b'>', start)
            if gt == -1:
                continue
            # Check what follows: whitespace then </div>
            after = html_lower[gt + 1:gt + 20].lstrip()
            if after.startswith(b'</div>'):
                return True
    return False


def _has_noscript_js_warning(html_bytes: bytes) -> bool:
    """Detect <noscript> blocks warning that JavaScript is required.

    This is a definitive SPA signal — the page explicitly says it needs JS.
    """
    return bool(_NOSCRIPT_JS_REQUIRED.search(html_bytes))


def _extract_embedded_json(html_bytes: bytes) -> str | None:
    """Extract pre-rendered JSON data from SSR framework script tags.

    Many SSR frameworks embed serialized page data as JSON:
    - Next.js: <script id="__NEXT_DATA__" type="application/json">{...}</script>
    - Nuxt: <script>window.__NUXT__={...}</script>

    Returns the JSON string if found, None otherwise. This JSON can be used
    as document content WITHOUT needing Playwright rendering.
    """
    # Try __NEXT_DATA__ first (more common, cleaner format)
    match = _NEXT_DATA_RE.search(html_bytes)
    if match:
        json_bytes = match.group(1).strip()
        if json_bytes:
            return json_bytes.decode("utf-8", errors="replace")

    # Try __NUXT__ assignment
    match = _NUXT_DATA_RE.search(html_bytes)
    if match:
        json_bytes = match.group(1).strip()
        if json_bytes:
            return json_bytes.decode("utf-8", errors="replace")

    return None


def _looks_like_js_shell(html_bytes: bytes, extracted_text: str) -> bool:
    """Detect JS-rendered SPAs that return an empty HTML shell.

    Returns True if ANY of these conditions hold:
    1. Original heuristic: short text + high script-to-HTML ratio
    2. Empty SPA framework mount point detected + short text
    3. <noscript> "enable JavaScript" warning + short text

    The text-length check (_SPA_MIN_TEXT_LEN) gates all signals to avoid
    false positives on pages that happen to use React but SSR properly.
    """
    if len(html_bytes) == 0:
        return False
    if len(extracted_text) >= _SPA_MIN_TEXT_LEN:
        return False

    html_lower = html_bytes.lower()

    # Signal 1: high script-to-HTML ratio (original heuristic)
    script_bytes = sum(
        len(seg) for seg in html_lower.split(b"<script")[1:]
    )
    if (script_bytes / len(html_bytes)) > _SPA_SCRIPT_RATIO:
        return True

    # Signal 2: empty SPA framework mount point
    if _has_empty_mount_point(html_lower):
        return True

    # Signal 3: noscript warning about JavaScript being required
    if _has_noscript_js_warning(html_bytes):
        return True

    return False


def _extract_text(
    resource: FetchedResource, *, method: str,
) -> tuple[str, str, dict, str, list[str]]:
    """Normalize extraction with optional Trafilatura path.

    Returns (text, markdown, metadata, method_used, warnings).
    """
    warnings: list[str] = []
    if "html" not in (resource.content_type or "").lower() and not resource.content_bytes:
        warnings.append("non-text or empty payload; extraction is best effort")
        return "", "", {}, "binary", warnings

    html_text = _decode_text(resource.content_bytes)
    trafilatura_preferred = method == "trafilatura" and resource.fetch_method != "render_playwright"

    text: str | None = None
    markdown: str = ""
    metadata: dict = {}
    used = "fallback_strip"

    if trafilatura_preferred:
        txt, md, meta = _extract_with_trafilatura(html_text, url=resource.requested_url)
        if txt:
            text = txt
            markdown = md
            metadata = meta
            used = "trafilatura"
        else:
            warnings.append("Trafilatura unavailable or extraction failed; using fallback")

    if text is None:
        text = _strip_html_tags(html_text)
        if not text:
            warnings.append("fallback extractor returned empty body")

    return text or "", markdown, metadata, used, warnings


def _run_async(coro):
    """Run an async coroutine from sync code, handling already-running event loops.

    Uses asyncio.run() when no event loop is running. Falls back to running
    in a new thread when called from within an existing event loop (e.g. Jupyter).
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running — safe to use asyncio.run()
        return asyncio.run(coro)

    # Event loop already running — run in a new thread with its own loop
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


class SourceFetcher:
    """Fetch web resources and preserve fetch metadata."""

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        user_agent_profile: str = "open_web_retrieval/0.4",
        client: httpx.Client | None = None,
        blocked_domains: set[str] | None = None,
        rate_limit_per_second: float = 2.0,
        tool_call_logger: ToolCallLogger | None = None,
        enable_antibot: bool = False,
        enable_auto_render: bool = True,
    ) -> None:
        """Construct a fetcher with injected HTTP transport.

        Args:
            blocked_domains: Set of domain names (without www. prefix) to reject
                immediately with a non-retryable FetchError.
            rate_limit_per_second: Maximum requests per second per domain.
                Set to 0 to disable rate limiting.
            enable_antibot: If True, escalate 403 responses to browser-based
                fetch via Crawl4AI. Requires crawl4ai to be installed.
        """
        if enable_antibot:
            try:
                import crawl4ai  # noqa: F401
            except ImportError:
                raise ImportError(
                    "crawl4ai is required for anti-bot escalation. "
                    "Install with: pip install open_web_retrieval[antibot]"
                )
        self._enable_antibot = enable_antibot
        self._enable_auto_render = enable_auto_render
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.user_agent_profile = user_agent_profile
        self._blocked_domains = (blocked_domains or set()) | KNOWN_BLOCKED_DOMAINS
        self._rate_limit = rate_limit_per_second
        self._last_request: dict[str, float] = {}  # domain -> monotonic timestamp
        self.metrics = FetchMetrics()
        self.tool_call_logger = tool_call_logger

    def _rate_limit_wait(self, domain: str) -> None:
        """Sleep if needed to respect per-domain rate limits."""
        if self._rate_limit <= 0:
            return
        now = time.monotonic()
        if domain in self._last_request:
            min_interval = 1.0 / self._rate_limit
            elapsed = now - self._last_request[domain]
            wait = max(0.0, min_interval - elapsed)
            if wait > 0:
                logger.debug("RATE_LIMIT domain=%s wait=%.2fs", domain, wait)
                time.sleep(wait)
                self.metrics.total_wait_seconds += wait
        self._last_request[domain] = time.monotonic()

    def _crawl4ai_fetch(self, url: str) -> FetchedResource:
        """Attempt browser-based fetch via Crawl4AI for anti-bot bypass.

        Uses AsyncWebCrawler with headless Chromium to bypass anti-bot
        protections that block plain HTTP requests. Raises FetchError
        on failure.
        """
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

        async def _fetch():
            browser_config = BrowserConfig(headless=True)
            crawler_config = CrawlerRunConfig(
                verbose=False,
            )
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=crawler_config)
                if not result.success:
                    raise FetchError(
                        f"crawl4ai failed: {result.error_message}",
                        retryable=False,
                        context={"url": url, "method": "crawl4ai"},
                    )
                html_bytes = result.html.encode("utf-8") if result.html else b""
                return FetchedResource(
                    requested_url=url,
                    final_url=result.url or url,
                    status=result.status_code or 200,
                    content_type="text/html",
                    content_bytes=html_bytes,
                    retrieved_at_utc=_utc_now(),
                    fetch_method="crawl4ai",
                    sha256=_hash_bytes(html_bytes),
                )

        return _run_async(_fetch())

    def fetch(
        self,
        request: FetchRequest,
        *,
        trace_id: str | None = None,
        task: str | None = None,
    ) -> FetchedResource:
        """Fetch the URL using direct HTTP with normalized provenance output.

        Raises FetchError with retryable=False for permanent failures (4xx auth/not-found,
        blocked domains) and retryable=True for transient failures (timeouts, 5xx, rate limits).

        On 429 responses, respects the Retry-After header and retries once.
        On 403 responses with enable_antibot=True, escalates to browser-based fetch.
        """
        call_id = make_tool_call_id()
        started_at = utc_now_iso()
        started_monotonic = time.monotonic() if self.tool_call_logger is not None else None

        # Check blocked domains before making any network request.
        domain = urlparse(request.url).netloc.removeprefix("www.")
        base_metrics = {
            "domain": domain,
            "render_mode": request.render_mode,
            "max_bytes": request.max_bytes,
        }
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider="playwright" if request.render_mode == "always" else "httpx",
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
                provider="httpx",
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
        self._rate_limit_wait(domain)

        headers = {"User-Agent": request.user_agent_profile}
        try:
            if request.render_mode == "always":
                response = self._render(request.url)
            else:
                response = self.client.get(request.url, headers=headers, follow_redirects=True)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.info("FETCH_TIMEOUT url=%s", request.url)
            self.metrics.failed += 1
            emit_tool_call(
                self.tool_call_logger,
                call_id=call_id,
                tool_name="open_web_retrieval",
                operation="fetch",
                provider="httpx",
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
                context={"url": request.url, "method": "httpx"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=call_id,
                    tool_name="open_web_retrieval",
                    operation="fetch",
                    provider="httpx",
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
                wait = _parse_retry_after(retry_after_header) if retry_after_header else _DEFAULT_RETRY_AFTER_SECONDS
                logger.info("RATE_LIMITED url=%s retry_after=%.1fs", request.url, wait)
                self.metrics.total_wait_seconds += wait
                time.sleep(wait)
                self.metrics.retried += 1
                retry_call_id = make_tool_call_id()
                retry_started_at = utc_now_iso()
                retry_started_monotonic = time.monotonic() if self.tool_call_logger is not None else None
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=retry_call_id,
                    tool_name="open_web_retrieval",
                    operation="fetch",
                    provider="httpx",
                    target=request.url,
                    status="started",
                    started_at=retry_started_at,
                    attempt=2,
                    task=task,
                    trace_id=trace_id,
                    metrics={**base_metrics, "retry_after_seconds": wait},
                )
                try:
                    response = self.client.get(request.url, headers=headers, follow_redirects=True)
                    response.raise_for_status()
                    emit_tool_call(
                        self.tool_call_logger,
                        call_id=retry_call_id,
                        tool_name="open_web_retrieval",
                        operation="fetch",
                        provider="httpx",
                        target=request.url,
                        status="succeeded",
                        started_at=retry_started_at,
                        ended_at=utc_now_iso(),
                        duration_ms_value=duration_ms(retry_started_monotonic) if retry_started_monotonic is not None else None,
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
                        provider="httpx",
                        target=request.url,
                        status="failed",
                        started_at=retry_started_at,
                        ended_at=utc_now_iso(),
                        duration_ms_value=duration_ms(retry_started_monotonic) if retry_started_monotonic is not None else None,
                        attempt=2,
                        task=task,
                        trace_id=trace_id,
                        metrics={**base_metrics, "http_status": 429, "retry_after_seconds": wait, "retryable": True},
                        error_type=retry_exc.__class__.__name__,
                        error_message=str(retry_exc),
                    )
                    raise FetchError(
                        f"HTTP 429 retry failed",
                        retryable=True,
                        context={"url": request.url, "status": 429, "retry_after": wait},
                    ) from retry_exc
            else:
                # Escalate 403 to browser-based fetch when antibot is enabled
                if exc.response.status_code == 403 and self._enable_antibot:
                    try:
                        logger.info("Escalating to crawl4ai for anti-bot: %s", request.url)
                        self.metrics.escalated += 1
                        resource = self._crawl4ai_fetch(request.url)
                        logger.info("FETCH_ESCALATED url=%s method=crawl4ai", request.url)
                        return resource
                    except Exception as antibot_exc:
                        logger.warning("crawl4ai escalation failed: %s", antibot_exc)
                        # Fall through to raise original FetchError

                retryable = exc.response.status_code not in NON_RETRYABLE_STATUS
                if retryable:
                    logger.info("FETCH_FAILED_RETRYABLE status=%d url=%s", exc.response.status_code, request.url)
                    self.metrics.failed += 1
                else:
                    logger.info("SKIP_PERMANENT status=%d url=%s", exc.response.status_code, request.url)
                    self.metrics.skipped_permanent += 1
                emit_tool_call(
                    self.tool_call_logger,
                    call_id=call_id,
                    tool_name="open_web_retrieval",
                    operation="fetch",
                    provider="httpx",
                    target=request.url,
                    status="failed",
                    started_at=started_at,
                    ended_at=utc_now_iso(),
                    duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
                    attempt=1,
                    task=task,
                    trace_id=trace_id,
                    metrics={**base_metrics, "http_status": exc.response.status_code, "retryable": retryable},
                    error_type="HTTPStatusError",
                    error_message=f"HTTP {exc.response.status_code}",
                )
                raise FetchError(
                    f"HTTP {exc.response.status_code}",
                    retryable=retryable,
                    context={"url": request.url, "status": exc.response.status_code},
                ) from exc
        except httpx.HTTPError as exc:
            self.metrics.failed += 1
            emit_tool_call(
                self.tool_call_logger,
                call_id=call_id,
                tool_name="open_web_retrieval",
                operation="fetch",
                provider="httpx",
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
                "fetch failed",
                retryable=True,
                context={"url": request.url, "method": "httpx"},
            ) from exc

        content = response.content
        if len(content) > request.max_bytes:
            content = content[: request.max_bytes]
        self.metrics.fetched += 1
        logger.info("FETCH status=%d url=%s method=%s bytes=%d", response.status_code, request.url, "playwright" if request.render_mode == "always" else "httpx", len(content))
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider="playwright" if request.render_mode == "always" else "httpx",
            target=request.url,
            status="succeeded",
            started_at=started_at,
            ended_at=utc_now_iso(),
            duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
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
            fetch_method="httpx",
            sha256=_hash_bytes(content),
        )

    def _render(self, url: str) -> httpx.Response:
        """Use Playwright HTML rendering when request render mode is mandatory."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RenderError(
                "playwright unavailable for mandatory render mode",
                context={"url": url},
            ) from exc

        # Render by launching a browser, then fetch the final page source as HTML.
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")
                html = page.content()
                final_url = page.url
                page.close()
                browser.close()
        except Exception as exc:
            raise RenderError(
                "playwright render failed",
                context={"url": url},
            ) from exc

        request = httpx.Request("GET", final_url)
        response = httpx.Response(
            status_code=200,
            content=html.encode("utf-8"),
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )
        return response

    def extract(
        self,
        resource: FetchedResource,
        *,
        method: str = "trafilatura",
        trace_id: str | None = None,
        task: str | None = None,
    ) -> ExtractedDocument:
        """Extract normalized text and provenance from fetched bytes."""
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
            metrics={"content_type": resource.content_type, "fetch_method": resource.fetch_method},
        )
        text, markdown, metadata, method_used, warnings = _extract_text(resource, method=method)
        document = ExtractedDocument(
            source_url=resource.requested_url,
            final_url=resource.final_url,
            title=metadata.get("title"),
            publisher_guess=metadata.get("sitename") or metadata.get("author"),
            published_at_guess=_parse_date_string(metadata.get("date")),
            text=text,
            markdown=markdown,
            document_type="html" if "html" in (resource.content_type or "").lower() else "unknown",
            extraction_method=method_used,
            warnings=warnings,
        )
        # Check for JS-rendered SPA: short text + script-heavy HTML → try embedded JSON, then Playwright
        if (
            self._enable_auto_render
            and resource.fetch_method != "render_playwright"
            and resource.fetch_method != "crawl4ai"
            and _looks_like_js_shell(resource.content_bytes, document.text)
        ):
            # Try embedded JSON first (Next.js __NEXT_DATA__, Nuxt __NUXT__) — much faster than Playwright
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
                    warnings=document.warnings + ["extracted embedded SSR JSON (no render needed)"],
                )
            else:
                # Fall back to Playwright rendering
                try:
                    logger.info(
                        "SPA_DETECTED url=%s text_len=%d — re-fetching with Playwright",
                        resource.requested_url,
                        len(document.text),
                    )
                    rendered_request = FetchRequest(
                        url=resource.requested_url,
                        render_mode="always",
                        user_agent_profile=self.user_agent_profile,
                    )
                    rendered_resource = self.fetch(rendered_request)
                    rendered_resource = FetchedResource(
                        requested_url=rendered_resource.requested_url,
                        final_url=rendered_resource.final_url,
                        status=rendered_resource.status,
                        content_type=rendered_resource.content_type,
                        content_bytes=rendered_resource.content_bytes,
                        retrieved_at_utc=rendered_resource.retrieved_at_utc,
                        fetch_method="render_playwright",
                        sha256=rendered_resource.sha256,
                    )
                    text, markdown, metadata, method_used, warnings = _extract_text(
                        rendered_resource, method=method
                    )
                    document = ExtractedDocument(
                        source_url=resource.requested_url,
                        final_url=rendered_resource.final_url,
                        title=metadata.get("title"),
                        publisher_guess=metadata.get("sitename") or metadata.get("author"),
                        published_at_guess=_parse_date_string(metadata.get("date")),
                        text=text,
                        markdown=markdown,
                        document_type="html",
                        extraction_method=f"{method_used}+render",
                        warnings=warnings + ["auto-rendered: original was JS shell"],
                    )
                    self.metrics.auto_rendered += 1
                    logger.info(
                        "SPA_RENDERED url=%s text_len=%d markdown_len=%d",
                        resource.requested_url,
                        len(document.text),
                        len(document.markdown),
                    )
                except Exception as exc:
                    logger.warning(
                        "SPA_RENDER_FAILED url=%s error=%s — keeping original extraction",
                        resource.requested_url,
                        exc,
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
            duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
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

    def close(self) -> None:
        """Release HTTP client resources."""
        if getattr(self, "_owns_client", False):
            self.client.close()

    def __del__(self) -> None:
        """Close owned HTTP client at object deletion."""
        self.close()


def _utc_now() -> Any:
    """Return an aware UTC timestamp."""
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)
