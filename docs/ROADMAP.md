# open_web_retrieval — Roadmap

**Status**: Active
**Last updated**: 2026-04-08

See `REQUIREMENTS.md` for capabilities inventory and success criteria.

---

## Where We Are

**v0.1 (shipped):** Basic pipeline works. Search (Brave/SearxNG) → Fetch (httpx) →
Extract (trafilatura) → Provenance. Pydantic contracts, caching, optional Playwright.

**v0.2 (shipped):** Resilient fetch. `FetchError.retryable` classifies HTTP errors
as permanent (401/403/404/410/451) or transient (429/5xx/timeout). Blocked domains
skip immediately. Plan #01 complete, 79 tests.

**v0.3 (shipped):** Robust fetch. Retry-After header respected on 429. Per-domain
rate limiting (2 req/s default). FetchMetrics counters. Plan #02 complete, 87 tests.

**v0.4 (shipped):** Enhanced extraction. Markdown output from trafilatura. Metadata
populated (title, author, date, sitename). Search result dedup by URL.
Plan #03 complete, 98 tests.

**v0.4.1 (shipped):** Hardening and v1.0 prep. Brave API error messages distinguish
401 (invalid key) from 429 (rate limited with Retry-After). py.typed marker.
trafilatura version pinned. Version bumped to 0.4.0. README rewrite with code
examples. CI via GitHub Actions (py3.10, py3.12). Plan #04 complete.

**v0.5 (shipped, 2026-03-25):** Crawl4AI anti-bot escalation. Optional `[antibot]` dep.
`enable_antibot=True` triggers browser-based fetch on HTTP 403. Escalation is not a
retry — it's a different mechanism. Plan #05 complete, 106 tests.


**v0.6 (shipped, 2026-03-26):** Enhanced SPA detection (framework mount points,
noscript detection, embedded JSON extraction), context manager protocol, cache
hardening (file locking, LRU eviction, stats), async support (AsyncSourceFetcher,
AsyncOpenWebRetrievalClient), integration test suite. Plan #06 complete, 143 tests.

**v0.7 (shipped, 2026-03-30):** Tavily provider parity. Added a first-class
Tavily search adapter, wired it into `OpenWebRetrievalClient`, and verified the
normalized contract with unit tests plus a live smoke query. Plan #10 complete.

**v0.8 (shipped, 2026-03-30):** Exa provider parity. Added a first-class Exa
search adapter, wired it into `OpenWebRetrievalClient`, and verified the deep-search
default with unit tests plus a live smoke query. Plan #11 complete.

**v0.8.1 (shipped, 2026-04-08):** Consumer-expressive retrieval controls.
`SearchQuery` now exposes typed shared controls for search depth, result
detail, detail budget, and corpus intent. Tavily and Exa honor those controls
through verified adapter request-body tests. Plan #15 complete.

**v0.8.2 (shipped, 2026-04-08):** Generic retrieval-instruction support.
`SearchQuery` now exposes one generic `retrieval_instruction` field for
provider-level ranking guidance. Exa maps it to `systemPrompt`; unsupported
providers fail loud instead of silently ignoring it. Plan #16 complete.

**What's next:** v1.0 (shareable library) is still gated on ROADMAP Phase 4. The
shared retrieval control surface is now typed and verified for Tavily and Exa,
including Exa retrieval instructions. The next justified provider work is only
new generic controls that a real consumer can prove it needs.

---

## The Path

### Evidence-Driven Maintenance: Consumer-Expressive Retrieval Controls

This is not a Tyler-specific branch. It is a shared-quality follow-up triggered
by real downstream needs:

- expand `SearchQuery` so consumers can declare retrieval depth, detail,
  and corpus intent through the shared contract
- add one generic retrieval-instruction field when a provider supports ranking
  guidance beyond raw query text
- verify via transport-capture tests that Tavily and Exa adapters honor those
  declared controls
- keep provider-specific execution inside the shared adapters rather than
  consumer-local wrappers

### v0.5: Anti-Bot Escalation (shipped)

Crawl4AI optional backend for 403 escalation. `pip install open_web_retrieval[antibot]`.
Gate passed: previously-blocked sites return content via Crawl4AI escalation.

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

**Note:** Steps 1.0.2 and 1.0.3 are partially addressed by Plan #04 (v0.4.1).

---

## SOTA Landscape (researched 2026-03-24)

| Tool | Relationship to us |
|------|-------------------|
| **Crawl4AI** | Optional escalation backend (v0.5). Free, OSS, anti-bot. Requires Playwright (~150MB). |
| **Firecrawl** | Cloud alternative. Better success rate (95% vs 90%) but proprietary anti-bot. Not self-hostable at full capability. |
| **Tavily** | Search API, not a fetcher. Complementary to Brave/SearxNG, not to our fetch layer. |
| **Jina Reader** | Markdown conversion. Could replace trafilatura for v0.4 but adds external dependency. |
| **retryhttp** | Transport-layer retry for httpx. Evaluated, deferred — hand-rolled classification simpler for our needs. |
| **httpx-retries** | Alternative to retryhttp. Evaluated, deferred — same reasoning. |

Full research: `docs/plans/01_fetch_resilience_and_crawl4ai.md`

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-03-24 | Evaluated `retryhttp`/`httpx-retries`, hand-rolled instead | Hand-rolled approach gave cleaner error classification and observability integration. |
| 2026-03-24 | Defer Crawl4AI to v0.5 | Most "blocked" sites are paywalls. Anti-bot is an arms race. Solve the 90% case first. |
| 2026-03-24 | Keep httpx+trafilatura as core stack | Community consensus: still the recommended "fast path." Browser-based tools for escalation only. |
| 2026-03-25 | Requirements before implementation | Wrote REQUIREMENTS.md to define consumers, boundaries, success criteria before building features. |
| 2026-03-25 | Bump to v0.4.0, not v1.0 | Version reflects feature state. v1.0 is a ROADMAP Phase 4 milestone requiring broader shareable-ecosystem readiness. |
| 2026-03-30 | Add Tavily as a direct adapter, not a framework wrapper | Thin JSON API, existing adapter pattern fits, and direct wrapping keeps observability under repo control. |
| 2026-03-30 | Add Exa as a direct adapter with `type="deep"` default | Live API shape fit the existing contract; deep search was the correct initial shared default. |
| 2026-04-08 | Expand retrieval controls only through the normalized contract | Consumers should declare what they need explicitly; provider adapters should honor those typed controls rather than rely on fixed defaults. |
| 2026-04-08 | Use one generic retrieval-instruction field instead of provider-specific prompt fields | Consumers need provider-level ranking guidance, but the shared boundary should stay generic and fail loud where unsupported. |
