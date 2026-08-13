# open_web_retrieval — Requirements

**Status**: Active
**Last updated**: 2026-08-12
**Owner**: Brian Mills

---

## What This Is

A shared Python library that gives any project the ability to search the web,
fetch pages, and extract clean text — with provenance, error classification,
and configurable resilience. It's shared infrastructure per the root CLAUDE.md:
"general capabilities any project uses."

## What This Is NOT

- Not a web crawler (no link-following, sitemaps, or recursive crawling)
- Not a scraping framework (no CSS selectors, no DOM manipulation)
- Not a general anti-bot bypass service (no CAPTCHA solving, no proxy rotation). Optional Crawl4AI escalation on HTTP 403 is available via `enable_antibot=True`, but is narrowly scoped to browser-based re-fetch, not full bypass infrastructure.
- Not a search engine (queries upstream services and source indexes; it does not
  build or own an index)

---

## Consumers

| Consumer | Uses | Needs |
|----------|------|-------|
| **research_v3 loop.py** | Search (Brave), Fetch, Extract | Fast search, resilient fetch (skip paywalls), clean text for LLM extraction |
| **research_v3 tools/brave_search.py** | Search (Brave) | Normalized search results |
| **sam_gov** (potential) | Search, Fetch | Government site fetching |
| **Future OSINT projects** | All | Full pipeline |

---

## Capabilities (current v0.12)

### Search — find URLs for a query

| Feature | Status | Notes |
|---------|--------|-------|
| Brave API search | **Shipped** | Via adapter |
| SearxNG search | **Shipped** | Via adapter |
| Tavily API search | **Shipped** | Via adapter |
| Exa API search | **Shipped** | Via adapter |
| Hacker News search | **Shipped** | Keyless, opt-in source-targeted adapter via the public Algolia index |
| arXiv search | **Shipped** | Keyless, opt-in source-targeted adapter via the Atom API |
| OpenAlex works search | **Shipped** | Opt-in keyword, native semantic, and works-only OQL modes; anonymous basic access with optional bearer API key; one paced retry of an identical read-only query on transport errors or HTTP 5xx; agent-tool results retain the public OpenAlex abstract as optional `raw_content` for provenance-marked consumer fallback |
| Reddit post search | **Shipped** | Opt-in OAuth script grant; subreddit scoping through `domains_allow`; credentials remain runtime-only |
| Normalized SearchHit output | **Shipped** | Provider-agnostic Pydantic model |
| Recency filtering | **Shipped** | `recency_days` param |
| Domain allow/deny lists | **Shipped** | `domains_allow`, `domains_deny` |
| Result deduplication across providers | **Shipped** | By URL, keep first occurrence (v0.4) |
| Search result caching | **Shipped** | TTL-based via `cache.py` |
| Shared provider pacing | **Shipped** | Process-wide request-start spacing and concurrency limits for keyless providers; paid providers unchanged by default |

### Fetch — retrieve page content from a URL

| Feature | Status | Notes |
|---------|--------|-------|
| HTTP fetch (httpx) | **Shipped** | Direct GET with follow-redirects |
| Playwright JS rendering | **Shipped** | Optional, `render_mode="always"` |
| Provenance (method, SHA256, timestamps) | **Shipped** | On FetchedResource |
| Byte limit enforcement | **Shipped** | `max_bytes` param |
| **HTTP error classification** | **Shipped** | `FetchError.retryable` field (v0.2) |
| **Retry with backoff** | **Shipped** | 429 respects Retry-After header, one retry (v0.3) |
| **Known-blocked domain skip** | **Shipped** | `blocked_domains` param on SourceFetcher (v0.2) |
| **Respect Retry-After header** | **Shipped** | Integer seconds and HTTP-date (v0.3) |
| Rate limiting (requests/second) | **Shipped** | Per-domain, default 2 req/s (v0.3) |
| Access-challenge fallback | **Shipped** | Detects 200/403/5xx Cloudflare-like interstitials; optional Crawl4AI then Jina Reader; explicit CAPTCHAs fail closed (v0.12) |
| SPA detection & auto-render | **Shipped** | Framework mount points, noscript detection, embedded JSON extraction (v0.6) |
| Hosted URL-to-Markdown retrieval (Jina Reader) | **Shipped** | Explicit one-URL adapter; consumer owns traversal and corpus capture |
| Robots.txt respect | **Not started** | Deferred to v1.0+ |

### Extract — turn HTML into clean text

| Feature | Status | Notes |
|---------|--------|-------|
| Trafilatura extraction | **Shipped** | Primary path |
| Fallback tag stripping | **Shipped** | When trafilatura fails |
| Markdown output | **Shipped** | `ExtractedDocument.markdown` field (v0.4) |
| Metadata extraction (title, author, date) | **Shipped** | Populated from trafilatura `bare_extraction()` (v0.4) |

### Cross-Cutting

| Feature | Status | Notes |
|---------|--------|-------|
| Full pipeline (search → fetch → extract) | **Shipped** | Via `OpenWebRetrievalClient` |
| Provenance on every operation | **Shipped** | Provider, URL, method, timestamps |
| Pydantic models for all contracts | **Shipped** | Frozen, validated |
| pip-installable | **Shipped** | Fresh clone installs with `python -m pip install -e .`; no workstation path is required |
| Context manager protocol | **Shipped** | `with SourceFetcher() as f:` and `with OpenWebRetrievalClient() as c:` (v0.6) |
| Async support | **Shipped** | `AsyncSourceFetcher`, `AsyncOpenWebRetrievalClient` (v0.6) |
| Cache hardening | **Shipped** | File locking, LRU eviction, `max_entries`, cache stats (v0.6) |
| Integration test suite | **Shipped** | E2E test script for diverse real URLs (v0.6) |

---

## Success Criteria

The library succeeds when:

1. **research_v3 loop completes F1 in <10 minutes** (currently times out at 20+ due to 403 retries)
2. **No consumer hand-rolls search, fetch, or extraction** — all go through this library
3. **Failures are classified** — consumers can distinguish "try again" from "give up"
4. **Provenance is complete** — every fetched page traces back to query → search hit → URL → content

## Failure Criteria

The library fails if:

1. It adds >500ms latency to the happy path (cooperative sites that return 200)
2. It requires Playwright/browser for basic HTTP fetches
3. It silently swallows errors (violates "fail loud" principle)
4. Consumers need to import httpx or trafilatura directly to work around limitations

---

## Priority Order

The proposed v0.9 capability slice is implemented on its feature branch. See
ROADMAP.md for version history and merge status.

---

## Boundaries

### This library owns:
- HTTP transport (httpx client lifecycle, retries, error classification)
- Search provider adapters (Brave, SearxNG, Tavily, Exa, Hacker News, arXiv, OpenAlex, Reddit)
- Explicit single-resource hosted fetch adapters, including Jina Reader
- Content extraction (trafilatura, fallback)
- Provenance tracking (what was fetched, when, how)
- Caching (TTL-based result cache)

### This library does NOT own:
- What to search for (consumer or its authorized agent decides queries and provider-native modes)
- What to do with extracted text (consumer's LLM pipeline)
- Domain-specific ranking or filtering (consumer layer)
- Link discovery, sitemap traversal, recursive crawling, and corpus storage
- Proxy management or rotation (out of scope for v0)
