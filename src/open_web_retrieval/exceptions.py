"""Custom exception classes for the open-web retrieval substrate."""

from __future__ import annotations


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


class RenderError(OpenWebRetrievalError):
    """Failure while rendering via browser automation."""

    error_code = "OPEN_WEB_RETRIEVAL_RENDER_ERROR"
