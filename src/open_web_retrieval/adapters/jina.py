"""Jina Reader adapter for URL-to-Markdown retrieval."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Literal
from urllib.parse import urlparse

import httpx

from open_web_retrieval.exceptions import FetchError
from open_web_retrieval.fetch_extract import _hash_bytes, _utc_now
from open_web_retrieval.models import FetchRequest, FetchedResource
from open_web_retrieval.observability import (
    ToolCallLogger,
    duration_ms,
    emit_tool_call,
    make_tool_call_id,
    utc_now_iso,
)


class JinaReaderAdapter:
    """Fetch one public URL as Markdown through Jina Reader.

    This is a single-resource retrieval adapter. Link discovery and crawl
    orchestration remain the consuming project's responsibility.
    """

    provider_name = "jina_reader"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float | None = 60.0,
        base_url: str = "https://r.jina.ai",
        client: httpx.Client | None = None,
        tool_call_logger: ToolCallLogger | None = None,
    ) -> None:
        """Configure the hosted Reader transport.

        An API key is optional. Without one, Jina's anonymous rate limit
        applies; callers that retrieve several URLs should pace requests.
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.tool_call_logger = tool_call_logger

    def _reader_url(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise FetchError(
                "Jina Reader requires an absolute http(s) URL",
                retryable=False,
                context={"url": source_url, "provider": self.provider_name},
            )
        return f"{self.base_url}/{source_url}"

    def fetch(
        self,
        request: FetchRequest,
        *,
        trace_id: str | None = None,
        task: str | None = None,
    ) -> FetchedResource:
        """Return Jina Reader's normalized Markdown in ``FetchedResource``."""
        call_id = make_tool_call_id()
        started_at = utc_now_iso()
        started_monotonic = time.monotonic() if self.tool_call_logger is not None else None
        reader_url = self._reader_url(request.url)
        base_metrics: dict[str, object] = {
            "source_url": request.url,
            "max_bytes": request.max_bytes,
        }
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider=self.provider_name,
            target=request.url,
            status="started",
            started_at=started_at,
            attempt=1,
            task=task,
            trace_id=trace_id,
            metrics=base_metrics,
        )

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.client.get(reader_url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise ValueError("missing data object")
            content = data.get("content")
            final_url = data.get("url")
            if not isinstance(content, str) or not isinstance(final_url, str):
                raise ValueError("missing string data.content or data.url")
        except httpx.TimeoutException as exc:
            error = FetchError(
                "Jina Reader request timed out",
                retryable=True,
                context={"url": request.url, "provider": self.provider_name},
            )
            self._emit_failure(
                error,
                call_id=call_id,
                started_at=started_at,
                started_monotonic=started_monotonic,
                task=task,
                trace_id=trace_id,
                metrics=base_metrics,
            )
            raise error from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status == 429 or status >= 500
            error = FetchError(
                f"Jina Reader request failed (HTTP {status})",
                retryable=retryable,
                context={
                    "url": request.url,
                    "provider": self.provider_name,
                    "status_code": status,
                },
            )
            self._emit_failure(
                error,
                call_id=call_id,
                started_at=started_at,
                started_monotonic=started_monotonic,
                task=task,
                trace_id=trace_id,
                metrics={**base_metrics, "http_status": status, "retryable": retryable},
            )
            raise error from exc
        except (ValueError, httpx.HTTPError) as exc:
            retryable = isinstance(exc, httpx.HTTPError)
            error = FetchError(
                "Jina Reader returned an invalid response" if not retryable else "Jina Reader request failed",
                retryable=retryable,
                context={"url": request.url, "provider": self.provider_name},
            )
            self._emit_failure(
                error,
                call_id=call_id,
                started_at=started_at,
                started_monotonic=started_monotonic,
                task=task,
                trace_id=trace_id,
                metrics={**base_metrics, "retryable": retryable},
            )
            raise error from exc

        content_bytes = content.encode("utf-8")[: request.max_bytes]
        resource = FetchedResource(
            requested_url=request.url,
            final_url=final_url,
            status=200,
            content_type="text/markdown; charset=utf-8",
            content_bytes=content_bytes,
            retrieved_at_utc=_utc_now(),
            fetch_method=self.provider_name,
            sha256=_hash_bytes(content_bytes),
        )
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider=self.provider_name,
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
                "byte_count": len(content_bytes),
                "final_url": final_url,
                "truncated": len(content.encode("utf-8")) > request.max_bytes,
            },
        )
        return resource

    def _emit_failure(
        self,
        error: FetchError,
        *,
        call_id: str,
        started_at: str,
        started_monotonic: float | None,
        task: str | None,
        trace_id: str | None,
        metrics: dict[str, object],
    ) -> None:
        emit_tool_call(
            self.tool_call_logger,
            call_id=call_id,
            tool_name="open_web_retrieval",
            operation="fetch",
            provider=self.provider_name,
            target=str(metrics["source_url"]),
            status="failed",
            started_at=started_at,
            ended_at=utc_now_iso(),
            duration_ms_value=duration_ms(started_monotonic) if started_monotonic is not None else None,
            attempt=1,
            task=task,
            trace_id=trace_id,
            metrics=metrics,
            error_type=error.__class__.__name__,
            error_message=str(error),
        )

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "JinaReaderAdapter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        self.close()
        return False
