"""open_web_retrieval package exports."""

from open_web_retrieval._version import __version__
from open_web_retrieval.access_alternatives import (
    classify_access_block,
    suggest_access_alternatives,
)
from open_web_retrieval.adapters.jina import JinaReaderAdapter
from open_web_retrieval.adapters.openalex import OpenAlexSearchAdapter
from open_web_retrieval.adapters.reddit import RedditSearchAdapter
from open_web_retrieval.async_client import AsyncOpenWebRetrievalClient
from open_web_retrieval.async_fetch import AsyncSourceFetcher
from open_web_retrieval.cache import CacheStats, DiskCache
from open_web_retrieval.client import OpenWebRetrievalClient, SourceRecordBatch
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    FetchError,
    OpenWebRetrievalError,
    ProviderUnavailableError,
    RenderError,
    RetrievalError,
)
from open_web_retrieval.fetch_extract import SourceFetcher
from open_web_retrieval.models import (
    AccessAlternative,
    AccessAlternativeKind,
    ExtractedDocument,
    FetchedResource,
    FetchMetrics,
    FetchRequest,
    OpenAlexQuery,
    OpenAlexSearchMode,
    ScholarlyWorkMetadata,
    SearchHit,
    SearchQuery,
    SourceRecord,
)
from open_web_retrieval.search_log import SearchLog

__all__ = [
    "AccessAlternative",
    "AccessAlternativeKind",
    "AsyncOpenWebRetrievalClient",
    "AsyncSourceFetcher",
    "CacheStats",
    "CapabilityNotSupportedError",
    "DiskCache",
    "ExtractedDocument",
    "FetchError",
    "FetchMetrics",
    "FetchRequest",
    "FetchedResource",
    "JinaReaderAdapter",
    "OpenAlexQuery",
    "OpenAlexSearchAdapter",
    "OpenAlexSearchMode",
    "OpenWebRetrievalClient",
    "OpenWebRetrievalError",
    "ProviderUnavailableError",
    "RedditSearchAdapter",
    "RenderError",
    "RetrievalError",
    "ScholarlyWorkMetadata",
    "SearchHit",
    "SearchLog",
    "SearchQuery",
    "SourceFetcher",
    "SourceRecord",
    "SourceRecordBatch",
    "__version__",
    "classify_access_block",
    "suggest_access_alternatives",
]

# Auto-register @tool decorated functions.
#
# The private ``llm_client`` package is an optional dependency, so its absence is
# tolerated -- but only the absence of the top-level package itself. A missing
# ``llm_client`` submodule such as ``llm_client.tools`` means an installed but
# incompatible llm_client, which is a real breakage, not an absent optional
# dependency. That, and every other import failure raised while loading the tools
# module -- including a transitive failure inside a module it imports -- is
# re-raised, per the fail-loud principle.
try:
    from open_web_retrieval.adapters.tools import (  # noqa: F401
        brave_search,
        exa_search,
        openalex_search,
        searxng_search,
        tavily_search,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional dep
    if exc.name != "llm_client":
        raise
