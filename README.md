# open_web_retrieval

Shared Python library for web search, fetch, and extraction with provenance.
Search the web, fetch pages, extract clean text or markdown — with error
classification, rate limiting, and full provenance tracking.

**What it is:** A reusable substrate that any project can `pip install` to get
normalized web retrieval without hand-rolling httpx + HTML parsing.

**What it is not:** Not a web crawler, not a scraping framework, not an anti-bot
bypass service.

Suggested reading order:

1. `CLAUDE.md`
2. `docs/ops/CAPABILITY_DECOMPOSITION.md`
3. `docs/REQUIREMENTS.md`
4. `docs/ROADMAP.md`
5. `docs/plans/CLAUDE.md`

## Shared Capability Ownership

`open_web_retrieval` is a shared-infrastructure repo, not just a library with
local examples. The repo-local source of record for what it owns, what it
exports to consumer repos, and what it should not absorb lives in
[`docs/ops/CAPABILITY_DECOMPOSITION.md`](./docs/ops/CAPABILITY_DECOMPOSITION.md).

## Installation

```bash
# Base (search + fetch only)
pip install -e ~/projects/open_web_retrieval

# With text/markdown extraction (trafilatura)
pip install -e "~/projects/open_web_retrieval[extract]"

# With browser rendering (Playwright)
pip install -e "~/projects/open_web_retrieval[render]"

# With @tool adapter registration (requires llm_client)
pip install -e "~/projects/open_web_retrieval[tools]"

# All optional deps (extract + render + antibot + tools)
pip install -e "~/projects/open_web_retrieval[all]"
```

## Quickstart

```python
from open_web_retrieval.client import OpenWebRetrievalClient
from open_web_retrieval.models import SearchQuery

client = OpenWebRetrievalClient(
    brave_api_key="your-key",
    tavily_api_key="your-tavily-key",
    blocked_domains={"paywalled-site.com", "pinterest.com"},
    rate_limit_per_second=2.0,
)

# Search
query = SearchQuery(query="Python web scraping best practices", providers=["tavily"], top_k=5)
hits = client.search(query)
for hit in hits:
    print(f"{hit.rank}. {hit.title} — {hit.url}")

# Full pipeline: search + fetch + extract
batch = client.retrieve(query, allow_partial=True)
for record in batch.records:
    doc = record.extracted_document
    if doc:
        print(f"## {doc.title}")
        print(f"Publisher: {doc.publisher_guess}")
        print(f"Date: {doc.published_at_guess}")
        print(f"Method: {doc.extraction_method}")
        print(doc.markdown[:500])  # Markdown output from trafilatura
```

## Features

| Feature | Details |
|---------|---------|
| **Search** | Brave API, SearxNG, Tavily, Exa. Normalized `SearchHit` contract. Dedup by URL across providers. |
| **Fetch** | httpx with error classification. `FetchError.retryable` distinguishes "try again" from "give up." |
| **Blocked domains** | Configurable set — rejected immediately without network request. |
| **Rate limiting** | Per-domain (default 2 req/s). Respects `Retry-After` header on 429. |
| **Extract** | Plain text and markdown via trafilatura. Title, author, date, sitename metadata. |
| **Render** | Optional Playwright fallback (`render_mode="always"`). Install with `[render]`. |
| **Provenance** | Every `SourceRecord` tracks provider, URL lineage, fetch method, extraction method. |
| **Caching** | Optional disk cache for search results and fetched pages (TTL-based). |
| **Observability** | `FetchMetrics` counters: fetched, skipped_blocked, skipped_permanent, retried, failed, total_wait_seconds. |

## Error Handling

All exceptions live in `open_web_retrieval.exceptions`:

```python
from open_web_retrieval.exceptions import FetchError

try:
    resource = client.fetcher.fetch(fetch_request)
except FetchError as e:
    if e.retryable:
        # 429, 5xx, timeout — try again later
        print(f"Transient: {e}")
    else:
        # 401, 403, 404, 410, 451, blocked domain — give up
        print(f"Permanent: {e}")
```

Error codes: `OPEN_WEB_RETRIEVAL_PROVIDER_UNAVAILABLE`,
`OPEN_WEB_RETRIEVAL_RETRIEVAL_ERROR`, `OPEN_WEB_RETRIEVAL_FETCH_ERROR`,
`OPEN_WEB_RETRIEVAL_RENDER_ERROR`, `OPEN_WEB_RETRIEVAL_CAPABILITY_UNSUPPORTED`.

## Configuration

```python
client = OpenWebRetrievalClient(
    brave_api_key="...",                    # Brave API key
    exa_api_key="...",                     # Exa API key
    searxng_base_url="http://localhost:8080",  # SearxNG instance
    tavily_api_key="...",                  # Tavily API key
    blocked_domains={"pinterest.com"},      # Skip without fetching
    rate_limit_per_second=2.0,              # Per-domain rate limit
    cache_dir="/tmp/owr_cache",             # Enable disk caching
    cache_ttl_seconds=3600,                 # Cache TTL (default 1 hour)
    timeout_seconds=10.0,                   # HTTP timeout
)
```


## Async Usage

For async workflows (e.g., inside an async web server or agent loop):

```python
import asyncio
from open_web_retrieval.async_client import AsyncOpenWebRetrievalClient
from open_web_retrieval.models import SearchQuery

async def main():
    async with AsyncOpenWebRetrievalClient(brave_api_key="your-key") as client:
        query = SearchQuery(query="async Python best practices", providers=["brave"], top_k=5)
        hits = await client.search(query)
        for hit in hits:
            print(f"{hit.rank}. {hit.title}")

asyncio.run(main())
```

Or use `AsyncSourceFetcher` directly:

```python
from open_web_retrieval.async_fetch import AsyncSourceFetcher
from open_web_retrieval.models import FetchRequest

async with AsyncSourceFetcher() as fetcher:
    result = await fetcher.fetch(FetchRequest(url="https://example.com"))
    print(result.content[:200])
```

## Context Managers

Both the sync and async clients support the context manager protocol for
clean resource management:

```python
# Sync
from open_web_retrieval.client import OpenWebRetrievalClient

with OpenWebRetrievalClient(brave_api_key="your-key") as client:
    hits = client.search(query)
# Resources cleaned up automatically

# Async
from open_web_retrieval.async_client import AsyncOpenWebRetrievalClient

async with AsyncOpenWebRetrievalClient(brave_api_key="your-key") as client:
    hits = await client.search(query)
```

## SPA Detection

The library auto-detects single-page applications (React, Vue, Angular, Next.js,
Nuxt) and handles them appropriately:

- **Framework mount points**: Detects empty `<div id="root">`, `<div id="app">`, etc.
- **Noscript tags**: Detects "enable JavaScript" messages in `<noscript>` elements.
- **Embedded JSON**: Extracts data from `__NEXT_DATA__` and `__NUXT__` script tags
  without needing a browser.

When SPA content is detected and Playwright is available (`[render]` extra),
the library automatically escalates to browser-based rendering.

## Cache Configuration

The disk cache supports max entry limits with LRU eviction and usage stats:

```python
from open_web_retrieval.cache import DiskCache

cache = DiskCache(
    cache_dir="/tmp/owr_cache",
    ttl_seconds=3600,       # Entries expire after 1 hour
    max_entries=1000,        # LRU eviction when exceeded
)

# Check cache stats
stats = cache.stats()
print(f"Entries: {stats['entries']}, Size: {stats['size_bytes']} bytes")
print(f"Hit rate: {stats.get('hit_rate', 0):.1%}")
```

File locking prevents corruption under concurrent access.

## Integration Tests

An end-to-end integration test script validates the library against real URLs:

```bash
# Run from repo root
python scripts/e2e_test.py
```

The script fetches diverse real URLs (cooperative sites, SPAs, government sites)
and validates output quality. Results are saved to `tests/fixtures/e2e_results.json`
for regression tracking.

## Observability: tool_call_logger

Both sync and async clients accept an optional `tool_call_logger` parameter for
structured observability. When provided, every search, fetch, and extract operation
emits a tool-call record (start, success/failure, duration, metrics).

```python
from open_web_retrieval.client import OpenWebRetrievalClient

# Any callable(record: dict) -> None works as a logger
def my_logger(record: dict) -> None:
    print(record)

client = OpenWebRetrievalClient(
    brave_api_key="your-key",
    tool_call_logger=my_logger,
)
```

**Runtime dependency:** The logger protocol is defined in
`open_web_retrieval.observability.ToolCallLogger` (a `Protocol` — any callable
matching the signature works). If you use `llm_client`'s tool-call logger, pass
it directly — the interface is compatible.

## Documentation

- [docs/ops/CAPABILITY_DECOMPOSITION.md](docs/ops/CAPABILITY_DECOMPOSITION.md) — repo-local ownership ledger for the shared retrieval substrate
- [REQUIREMENTS.md](docs/REQUIREMENTS.md) — what the library does and doesn't do
- [ROADMAP.md](docs/ROADMAP.md) — version history and future plans
- [SOTA_RESEARCH.md](docs/SOTA_RESEARCH.md) — landscape analysis (Crawl4AI, Firecrawl, Tavily, etc.)

## Tavily Notes

Tavily search uses the same normalized search contract:

```python
query = SearchQuery(
    query="PFAS drinking water EPA limits",
    providers=["tavily"],
    top_k=3,
    recency_days=30,
    domains_allow=["epa.gov"],
)
hits = client.search(query)
```

Provider-only extras such as answer summaries or follow-up suggestions remain in
`SearchHit.raw_payload` instead of expanding the base `SearchHit` contract.

## Exa Notes

Exa search is also available through the same normalized search contract:

```python
query = SearchQuery(
    query="UBI labor force participation",
    providers=["exa"],
    top_k=3,
    recency_days=30,
    domains_allow=["oecd.org", "worldbank.org", "nber.org"],
)
hits = client.search(query)
```

The shared Exa adapter uses `type="deep"` by default. Exa-specific fields such as
`highlights`, `author`, and `output` remain in `SearchHit.raw_payload`.
