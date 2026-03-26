# open_web_retrieval — Roadmap

**Status**: Active
**Last updated**: 2026-03-25

See `REQUIREMENTS.md` for capabilities inventory and success criteria.

---

## Where We Are

**v0.1 (shipped):** Basic pipeline works. Search (Brave/SearxNG) → Fetch (httpx) →
Extract (trafilatura) → Provenance. Pydantic contracts, caching, optional Playwright.

**v0.2 (shipped, 2026-03-25):** Resilient fetch. `FetchError.retryable` classifies
HTTP errors. Blocked domains skip immediately. Consumer (research_v3 loop.py) checks
`retryable` before retrying. Plan #01 complete, 79 tests pass.

**What's next:** The library can run single questions but isn't production-ready for
sustained autonomous operation — no rate limiting, no Retry-After respect, no fetch
metrics, no robots.txt.

---

## The Path

### v0.2: Resilient Fetch (unblocks research_v3 eval)

**Goal:** Consumers can distinguish "try again" from "give up." Cooperative sites
work exactly as before. Paywalled sites fail fast.

| Step | What | How |
|------|------|-----|
| 0.2.1 | Add `retryable` field to `FetchError` | `FetchError(retryable=True\|False)` |
| 0.2.2 | Classify HTTP status in `SourceFetcher.fetch()` | 401/403/404/410/451 = permanent. 429/500/502/503/504 = retryable. |
| 0.2.3 | Add `blocked_domains` param to `SourceFetcher` | Configurable set, skip immediately with `retryable=False` |
| 0.2.4 | Wire `retryhttp` or `httpx-retries` for transport retry | Replaces consumer-side retry loops. Respects classification. |

**Gate:** research_v3 loop completes F1 in <10 minutes. `FetchError.retryable` is
checked by at least one consumer.

**Failure mode:** If `retryhttp` doesn't integrate cleanly with our httpx.Client
lifecycle, fall back to manual status code check in `fetch()` (~20 lines).

**Not in v0.2:** Retry-After header, rate limiting, markdown output, Crawl4AI.

### v0.3: Robust Fetch (production quality)

**Goal:** Polite, observable, and self-regulating. Can run unsupervised for hours.

| Step | What | Why |
|------|------|-----|
| 0.3.1 | Respect `Retry-After` header on 429 | Brave API and target sites send this. Ignoring it = getting banned. |
| 0.3.2 | Per-host rate limiting | Prevent overwhelming any single host. Configurable default (e.g., 2 req/s). |
| 0.3.3 | Fetch metrics (success/fail/skip counts) | Observable. Consumers can log or alert. |
| 0.3.4 | Robots.txt respect (optional, default on) | Ethical default. Configurable opt-out for known-safe targets. |

**Gate:** Library can run a 7-question eval batch (~50 fetches) without hitting
rate limits or getting IP-banned.

**Failure mode:** If per-host rate limiting adds measurable latency to cooperative
sites, make it configurable per-domain (fast default, slow for known-strict hosts).

### v0.4: Enhanced Extraction

**Goal:** Output is LLM-ready without consumer post-processing.

| Step | What | Why |
|------|------|-----|
| 0.4.1 | Markdown output option | Consumers (research_v3, future agents) want markdown, not raw text. Crawl4AI and Jina Reader both output markdown — this is table stakes. |
| 0.4.2 | Search result deduplication | When using Brave + SearxNG, same URL appears twice. Dedup by URL, keep highest-ranked. |
| 0.4.3 | Structured metadata extraction | Author, publish date, canonical URL — trafilatura already extracts these but we don't surface them well. |

**Gate:** `ExtractedDocument` has a `markdown` field. Consumers don't need to
post-process raw text.

### v0.5: Anti-Bot Escalation (only if needed)

**Goal:** Fetch sites that actively block automated access, when the content is
publicly available (not paywalled).

| Step | What | Why |
|------|------|-----|
| 0.5.1 | Crawl4AI as optional backend | `pip install open_web_retrieval[antibot]`. Used ONLY when httpx gets 403 on a non-paywall site. |
| 0.5.2 | Escalation logic in SourceFetcher | httpx first (fast) → Crawl4AI (slow, browser-based) → fail. |
| 0.5.3 | Memory management for browser instances | Crawl4AI uses ~200MB RAM per browser. Recycle contexts every 10 pages. |

**Gate:** At least one previously-blocked site returns content via Crawl4AI escalation.

**Failure mode:** Crawl4AI's anti-bot degrades as Cloudflare updates (FlareSolverr
saw 90%→30% within weeks). If bypass rates <50%, this feature is not worth the
~200MB RAM cost. Pivot: accept that some sites are inaccessible and skip them.

**Decision point:** Don't build v0.5 until v0.2 proves insufficient. Most "blocked"
sites in research_v3 are paywalls (Reuters, WSJ), not anti-bot. Paywalls won't
serve content regardless of browser tricks.

### v1.0: Shareable Library

**Goal:** Part of the 6-repo shareable ecosystem (ROADMAP Phase 4).

| Step | What | Why |
|------|------|-----|
| 1.0.1 | Strip Brian-specific paths and config | General-purpose library |
| 1.0.2 | README with quickstart and examples | Someone can `pip install` and use in 5 minutes |
| 1.0.3 | CI (GitHub Actions) | Tests run on push |
| 1.0.4 | Versioned releases on PyPI or GitHub | Consumers pin to a version |

**Gate:** Someone unfamiliar with the codebase can install and use the library
from the README alone.

---

## SOTA Landscape (researched 2026-03-24)

| Tool | Relationship to us |
|------|-------------------|
| **Crawl4AI** | Optional escalation backend (v0.5). Free, OSS, anti-bot. Requires Playwright (~150MB). |
| **Firecrawl** | Cloud alternative. Better success rate (95% vs 90%) but proprietary anti-bot. Not self-hostable at full capability. |
| **Tavily** | Search API, not a fetcher. Complementary to Brave/SearxNG, not to our fetch layer. |
| **Jina Reader** | Markdown conversion. Could replace trafilatura for v0.4 but adds external dependency. |
| **retryhttp** | Transport-layer retry for httpx. Use in v0.2 instead of hand-rolling. |
| **httpx-retries** | Alternative to retryhttp. Transport-layer, configurable status codes. |

Full research: `docs/plans/01_fetch_resilience_and_crawl4ai.md`

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-03-24 | Use `retryhttp` or `httpx-retries` for v0.2, not hand-rolled | Both classify 403 as non-retryable out of the box. ~5 lines vs ~50. |
| 2026-03-24 | Defer Crawl4AI to v0.5 | Most "blocked" sites are paywalls. Anti-bot is an arms race. Solve the 90% case first. |
| 2026-03-24 | Keep httpx+trafilatura as core stack | Community consensus: still the recommended "fast path." Browser-based tools for escalation only. |
| 2026-03-25 | Requirements before implementation | Wrote REQUIREMENTS.md to define consumers, boundaries, success criteria before building features. |
