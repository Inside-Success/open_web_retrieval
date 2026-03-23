"""open_web_retrieval package exports."""

from open_web_retrieval.cache import DiskCache
from open_web_retrieval.client import OpenWebRetrievalClient, SourceRecordBatch
from open_web_retrieval.models import (
    ExtractedDocument,
    FetchRequest,
    FetchedResource,
    SearchHit,
    SearchQuery,
    SourceRecord,
)
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RetrievalError,
)

__all__ = [
    "DiskCache",
    "CapabilityNotSupportedError",
    "ExtractedDocument",
    "FetchRequest",
    "FetchedResource",
    "OpenWebRetrievalClient",
    "OpenWebRetrievalError",
    "ProviderUnavailableError",
    "RetrievalError",
    "SearchHit",
    "SearchQuery",
    "SourceRecord",
    "SourceRecordBatch",
]
