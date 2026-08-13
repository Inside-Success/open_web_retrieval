"""Small helper layer for optional shared tool-call observability.

This module stays intentionally narrow. Wave 0 only needs enough structure to
emit started/succeeded/failed rows for search, fetch, and extract boundaries
when a caller supplies a shared logger.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from time import monotonic
from uuid import uuid4


ToolCallLogger = Callable[[object], None]


def make_tool_call_id() -> str:
    """Return a stable id for one operation attempt."""

    return f"toolcall_{uuid4().hex}"


def utc_now_iso() -> str:
    """Return an aware UTC ISO timestamp for tool-call records."""

    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def duration_ms(started_monotonic: float) -> int:
    """Return elapsed wall time in milliseconds from a monotonic start."""

    return max(0, int(round((monotonic() - started_monotonic) * 1000)))


def query_sha256(query: str) -> str:
    """Return a stable content hash for search queries."""

    return sha256(query.encode("utf-8")).hexdigest()


def compact_query_target(query: str, *, max_chars: int = 96) -> str:
    """Return a compact, SQL-readable query target preview."""

    compact = " ".join(query.split())
    if len(compact) > max_chars:
        compact = compact[: max_chars - 3] + "..."
    return f"query:{compact}"


def emit_tool_call(
    logger: ToolCallLogger | None,
    *,
    call_id: str,
    tool_name: str,
    operation: str,
    status: str,
    started_at: str,
    provider: str | None = None,
    target: str | None = None,
    ended_at: str | None = None,
    duration_ms_value: int | None = None,
    attempt: int = 1,
    task: str | None = None,
    trace_id: str | None = None,
    metrics: dict[str, object] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Emit one shared tool-call record when a logger is configured.

    Logging is optional for the retrieval library itself, but once a caller
    provides a logger the contract becomes strict and llm_client must be
    importable so we can construct the shared typed record.
    """

    if logger is None:
        return
    try:
        from llm_client.observability.tool_calls import ToolCallResult
    except ModuleNotFoundError as exc:  # pragma: no cover - environment misconfiguration
        raise RuntimeError("tool-call logging requires llm_client to be installed") from exc

    logger(
        ToolCallResult(
            call_id=call_id,
            tool_name=tool_name,
            operation=operation,
            provider=provider,
            target=target,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms_value,
            attempt=attempt,
            task=task,
            trace_id=trace_id,
            metrics=dict(metrics or {}),
            error_type=error_type,
            error_message=error_message,
        )
    )


__all__ = [
    "ToolCallLogger",
    "compact_query_target",
    "duration_ms",
    "emit_tool_call",
    "make_tool_call_id",
    "query_sha256",
    "utc_now_iso",
]
