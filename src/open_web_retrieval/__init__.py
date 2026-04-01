"""open_web_retrieval package exports."""

__version__ = "0.8.0"

from open_web_retrieval.async_client import AsyncOpenWebRetrievalClient
from open_web_retrieval.async_fetch import AsyncSourceFetcher
from open_web_retrieval.cache import CacheStats, DiskCache
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
    "AsyncOpenWebRetrievalClient",
    "AsyncSourceFetcher",
    "CacheStats",
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
    "__version__",
]

# Auto-register @tool decorated functions
try:
    from open_web_retrieval.adapters.tools import brave_search, searxng_search, tavily_search, exa_search  # noqa: F401
except ImportError:
    pass  # llm_client not installed
