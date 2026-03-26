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
    FetchError,
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RenderError,
    RetrievalError,
)
from open_web_retrieval.fetch_extract import SourceFetcher
from open_web_retrieval.models import FetchMetrics

__all__ = [
    "DiskCache",
    "CapabilityNotSupportedError",
    "ExtractedDocument",
    "FetchRequest",
    "FetchedResource",
    "OpenWebRetrievalClient",
    "OpenWebRetrievalError",
    "ProviderUnavailableError",
    "FetchError",
    "FetchMetrics",
    "RenderError",
    "RetrievalError",
    "SourceFetcher",
    "SearchHit",
    "SearchQuery",
    "SourceRecord",
    "SourceRecordBatch",
]
