"""Fetch and extraction primitives for retrieved web resources."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import httpx

from open_web_retrieval.exceptions import FetchError, OpenWebRetrievalError, RenderError
from open_web_retrieval.models import (
    ExtractedDocument,
    FetchRequest,
    FetchedResource,
)


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


def _extract_with_trafilatura(html_text: str) -> str | None:
    """Attempt Trafilatura extraction and return a plain-text body."""
    try:
        from trafilatura import extract

        extracted = extract(html_text)
        if extracted:
            return extracted
    except ModuleNotFoundError:
        return None
    except Exception:
        return None
    return None


def _extract_text(resource: FetchedResource, *, method: str) -> tuple[str, str, list[str]]:
    """Normalize extraction with optional Trafilatura path.

    Returns body text, method used, and warnings.
    """
    warnings: list[str] = []
    if "html" not in (resource.content_type or "").lower() and not resource.content_bytes:
        warnings.append("non-text or empty payload; extraction is best effort")
        return "", "binary", warnings

    html_text = _decode_text(resource.content_bytes)
    trafilatura_preferred = method == "trafilatura" and resource.fetch_method != "render_playwright"

    extracted = None
    used = "fallback_strip"
    if trafilatura_preferred:
        extracted = _extract_with_trafilatura(html_text)
        if extracted:
            used = "trafilatura"
        else:
            warnings.append("Trafilatura unavailable or extraction failed; using fallback")

    if extracted is None:
        extracted = _strip_html_tags(html_text)
        if not extracted:
            warnings.append("fallback extractor returned empty body")
    return extracted or "", used, warnings


class SourceFetcher:
    """Fetch web resources and preserve fetch metadata."""

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        user_agent_profile: str = "open_web_retrieval/0.1",
        client: httpx.Client | None = None,
    ) -> None:
        """Construct a fetcher with injected HTTP transport."""
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.user_agent_profile = user_agent_profile

    def fetch(self, request: FetchRequest) -> FetchedResource:
        """Fetch the URL using direct HTTP with normalized provenance output."""
        headers = {"User-Agent": request.user_agent_profile}
        try:
            if request.render_mode == "always":
                response = self._render(request.url)
            else:
                response = self.client.get(request.url, headers=headers, follow_redirects=True)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FetchError(
                "fetch timed out",
                context={"url": request.url, "method": "httpx"},
            ) from exc
        except httpx.HTTPError as exc:
            raise FetchError(
                "fetch failed",
                context={"url": request.url, "method": "httpx"},
            ) from exc

        content = response.content
        if len(content) > request.max_bytes:
            content = content[: request.max_bytes]
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
        text, method_used, warnings = _extract_text(resource, method=method)
        return ExtractedDocument(
            source_url=resource.requested_url,
            final_url=resource.final_url,
            title=None,
            publisher_guess=None,
            published_at_guess=None,
            text=text,
            document_type="html" if "html" in (resource.content_type or "").lower() else "unknown",
            extraction_method=method_used,
            warnings=warnings,
        )

    def close(self) -> None:
        """Release HTTP client resources."""
        if self._owns_client:
            self.client.close()

    def __del__(self) -> None:
        """Close owned HTTP client at object deletion."""
        self.close()


def _utc_now() -> Any:
    """Return an aware UTC timestamp."""
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)

