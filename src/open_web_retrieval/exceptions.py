"""Custom exception classes for the open-web retrieval substrate."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from open_web_retrieval.models import AccessAlternative

FetchBlockReason = Literal[
    "access_denied",
    "challenge_detected",
    "captcha_required",
]


class OpenWebRetrievalError(RuntimeError):
    """Base class for all retrieval-layer failures."""

    error_code: str = "OPEN_WEB_RETRIEVAL_ERROR"

    def __init__(self, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.context = context or {}


class ProviderUnavailableError(OpenWebRetrievalError):
    """Provider configuration or connectivity is unavailable."""

    error_code = "OPEN_WEB_RETRIEVAL_PROVIDER_UNAVAILABLE"


class RetrievalError(OpenWebRetrievalError):
    """General retrieval failure after entering provider/fetch/extract flow."""

    error_code = "OPEN_WEB_RETRIEVAL_RETRIEVAL_ERROR"


class CapabilityNotSupportedError(OpenWebRetrievalError):
    """Requested capability is intentionally unsupported."""

    error_code = "OPEN_WEB_RETRIEVAL_CAPABILITY_UNSUPPORTED"


class FetchError(OpenWebRetrievalError):
    """Failure while fetching remote content."""

    error_code = "OPEN_WEB_RETRIEVAL_FETCH_ERROR"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        block_reason: FetchBlockReason | None = None,
        context: dict[str, object] | None = None,
        alternatives: Sequence[AccessAlternative] | None = None,
    ) -> None:
        resolved_alternatives = tuple(alternatives or ())
        source_url = (context or {}).get("url")
        if alternatives is None and block_reason is not None and isinstance(source_url, str):
            from open_web_retrieval.access_alternatives import (
                suggest_access_alternatives,
            )

            resolved_alternatives = suggest_access_alternatives(source_url, block_reason)
        enriched_context = dict(context or {})
        if resolved_alternatives:
            enriched_context["alternatives"] = [
                alternative.model_dump(mode="json")
                for alternative in resolved_alternatives
            ]
        super().__init__(message, context=enriched_context)
        self.retryable = retryable
        self.block_reason = block_reason
        self.alternatives = resolved_alternatives


class RenderError(OpenWebRetrievalError):
    """Failure while rendering via browser automation."""

    error_code = "OPEN_WEB_RETRIEVAL_RENDER_ERROR"
