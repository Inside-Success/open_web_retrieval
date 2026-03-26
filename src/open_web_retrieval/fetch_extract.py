"""Fetch and extraction primitives for retrieved web resources."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

# HTTP status codes that indicate permanent failures — retrying won't help.
NON_RETRYABLE_STATUS = {401, 403, 404, 410, 451}

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
        doc = bare_extraction(html_text, url=url, with_metadata=True)

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
                     include_tables=True, url=url)

        return (txt, _strip_frontmatter(md) if md else "", metadata)
    except Exception as exc:
        logger.warning("trafilatura extraction failed: %s", exc)
        return ("", "", {})


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
    ) -> None:
        """Construct a fetcher with injected HTTP transport.

        Args:
            blocked_domains: Set of domain names (without www. prefix) to reject
                immediately with a non-retryable FetchError.
            rate_limit_per_second: Maximum requests per second per domain.
                Set to 0 to disable rate limiting.
        """
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.user_agent_profile = user_agent_profile
        self._blocked_domains = blocked_domains or set()
        self._rate_limit = rate_limit_per_second
        self._last_request: dict[str, float] = {}  # domain -> monotonic timestamp
        self.metrics = FetchMetrics()

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
                time.sleep(wait)
                self.metrics.total_wait_seconds += wait
        self._last_request[domain] = time.monotonic()

    def fetch(self, request: FetchRequest) -> FetchedResource:
        """Fetch the URL using direct HTTP with normalized provenance output.

        Raises FetchError with retryable=False for permanent failures (4xx auth/not-found,
        blocked domains) and retryable=True for transient failures (timeouts, 5xx, rate limits).

        On 429 responses, respects the Retry-After header and retries once.
        """
        # Check blocked domains before making any network request.
        domain = urlparse(request.url).netloc.removeprefix("www.")
        if domain in self._blocked_domains:
            self.metrics.skipped_blocked += 1
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
            self.metrics.failed += 1
            raise FetchError(
                "fetch timed out",
                retryable=True,
                context={"url": request.url, "method": "httpx"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                # Respect Retry-After header and retry once.
                retry_after_header = exc.response.headers.get("Retry-After")
                wait = _parse_retry_after(retry_after_header) if retry_after_header else _DEFAULT_RETRY_AFTER_SECONDS
                self.metrics.total_wait_seconds += wait
                time.sleep(wait)
                self.metrics.retried += 1
                try:
                    response = self.client.get(request.url, headers=headers, follow_redirects=True)
                    response.raise_for_status()
                except (httpx.HTTPError, httpx.TimeoutException) as retry_exc:
                    self.metrics.failed += 1
                    raise FetchError(
                        f"HTTP 429 retry failed",
                        retryable=True,
                        context={"url": request.url, "status": 429, "retry_after": wait},
                    ) from retry_exc
            else:
                retryable = exc.response.status_code not in NON_RETRYABLE_STATUS
                if retryable:
                    self.metrics.failed += 1
                else:
                    self.metrics.skipped_permanent += 1
                raise FetchError(
                    f"HTTP {exc.response.status_code}",
                    retryable=retryable,
                    context={"url": request.url, "status": exc.response.status_code},
                ) from exc
        except httpx.HTTPError as exc:
            self.metrics.failed += 1
            raise FetchError(
                "fetch failed",
                retryable=True,
                context={"url": request.url, "method": "httpx"},
            ) from exc

        content = response.content
        if len(content) > request.max_bytes:
            content = content[: request.max_bytes]
        self.metrics.fetched += 1
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

    def extract(self, resource: FetchedResource, *, method: str = "trafilatura") -> ExtractedDocument:
        """Extract normalized text and provenance from fetched bytes."""
        text, markdown, metadata, method_used, warnings = _extract_text(resource, method=method)
        return ExtractedDocument(
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
