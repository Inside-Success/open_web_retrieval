"""Pydantic schema models for shared open-web retrieval contracts."""

from __future__ import annotations
from dataclasses import dataclass, field

from datetime import datetime
from typing import Any
from typing import Literal
from typing import Mapping
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from open_web_retrieval._version import __version__

# Derive user-agent default from the single-source version constant.
_DEFAULT_USER_AGENT = f"open_web_retrieval/{__version__}"




@dataclass
class FetchMetrics:
    """Counters for fetch operations. Consumers read these for observability."""

    fetched: int = 0
    skipped_blocked: int = 0
    skipped_permanent: int = 0
    retried: int = 0
    failed: int = 0
    total_wait_seconds: float = 0.0
    escalated: int = 0
    auto_rendered: int = 0  # SPA detection escalation (Playwright re-fetch or embedded JSON)

ProviderName = Literal["brave", "searxng", "tavily", "exa"]
RenderMode = Literal["never", "auto", "always"]
SearchDepth = Literal["basic", "advanced"]
ResultDetail = Literal["summary", "chunks"]
SearchCorpus = Literal[
    "general",
    "news",
    "academic",
    "company",
    "pdf",
    "github",
    "people",
    "personal_site",
    "financial_report",
]


class SearchQuery(BaseModel):
    """Search request used by all provider adapters.

    Keep this small and explicit. Consumer repos should place domain heuristics above
    this contract in their own workflow layer.
    """

    query: str = Field(min_length=1, description="Search query string.")
    providers: Sequence[ProviderName] = ("brave", "searxng")
    top_k: int = Field(default=10, ge=1, le=50, description="Maximum requested hits.")
    recency_days: int | None = Field(default=None, ge=1, description="Optional recency limit in days.")
    locale: str | None = Field(default=None, description="Optional provider locale/country hint.")
    search_depth: SearchDepth | None = Field(
        default=None,
        description="Optional provider-agnostic search-depth hint. Use `basic` for lighter/faster retrieval and `advanced` for deeper recall.",
    )
    result_detail: ResultDetail | None = Field(
        default=None,
        description="Optional detail mode. Use `summary` for lightweight result snippets and `chunks` for richer passage/highlight retrieval when supported.",
    )
    detail_budget: int | None = Field(
        default=None,
        ge=1,
        le=3,
        description="Optional per-result detail budget used when `result_detail` requests richer passage/highlight retrieval.",
    )
    corpus: SearchCorpus | None = Field(
        default=None,
        description="Optional corpus/category hint for providers that support category-aware retrieval.",
    )
    retrieval_instruction: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional provider-level retrieval/ranking guidance. Use this when a "
            "provider supports a separate instruction surface beyond raw query text."
        ),
    )
    domains_allow: Sequence[str] = ()
    domains_deny: Sequence[str] = ()

    model_config = ConfigDict(frozen=True)

    @field_validator("providers")
    @classmethod
    def ensure_provider(cls, providers: Sequence[ProviderName]) -> tuple[ProviderName, ...]:
        """Normalize provider order and reject empty provider sets."""
        if not providers:
            raise ValueError("At least one provider is required.")
        unique = tuple(dict.fromkeys(providers))
        return unique

    @field_validator("detail_budget")
    @classmethod
    def ensure_detail_budget_matches_mode(cls, detail_budget: int | None, info) -> int | None:
        """Reject chunk budgets that contradict an explicit summary request."""
        if detail_budget is None:
            return None
        result_detail = info.data.get("result_detail")
        if result_detail == "summary":
            raise ValueError("detail_budget requires result_detail='chunks' or an unspecified provider default")
        return detail_budget


class SearchHit(BaseModel):
    """Single normalized search result."""

    provider: ProviderName
    query: str
    title: str | None = None
    url: str
    snippet: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    rank: int = 0
    score_hint: float | None = None
    language: str | None = None
    raw_payload: Mapping[str, Any] | None = None

    model_config = ConfigDict(frozen=True)


class FetchRequest(BaseModel):
    """Normalized request for open-web fetch."""

    url: str
    render_mode: RenderMode = "auto"
    user_agent_profile: str = _DEFAULT_USER_AGENT
    max_bytes: int = Field(default=8_000_000, ge=1, le=50_000_000)

    model_config = ConfigDict(frozen=True)


class FetchedResource(BaseModel):
    """Raw fetched resource with provenance and transport metadata."""

    requested_url: str
    final_url: str
    status: int
    content_type: str | None = None
    content_bytes: bytes
    retrieved_at_utc: datetime
    fetch_method: str = "httpx"
    sha256: str

    model_config = ConfigDict(frozen=True)


class ExtractedDocument(BaseModel):
    """Text-normalized and provenance-rich extraction output."""

    source_url: str
    final_url: str
    title: str | None = None
    publisher_guess: str | None = None
    published_at_guess: datetime | None = None
    text: str
    markdown: str = ""
    document_type: str
    extraction_method: str
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)


class SourceRecord(BaseModel):
    """Cross-step aggregate of search + fetch + extraction."""

    query: str
    search_hit: SearchHit
    fetched_resource: FetchedResource | None = None
    extracted_document: ExtractedDocument | None = None
    provenance: Mapping[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)
