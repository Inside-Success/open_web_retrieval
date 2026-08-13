# open_web_retrieval — Roadmap

**Status**: Active
**Last updated**: 2026-08-13

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

**v0.12 (shipped, 2026-08-13):** Typed public-page access-challenge detection.
Cloudflare-like interstitials, including HTTP 200 challenge pages, can escalate
through opt-in Crawl4AI and Jina Reader fallbacks with attempt provenance.
Explicit CAPTCHAs fail closed; proxy rotation, fingerprint evasion, credential
reuse, login bypass, and paywall bypass remain out of scope.

**M3 OpenAlex resilience slice (in review, 2026-08-13):** The adapter retries
one identical, read-only keyword, semantic, or OQL request after a transport
failure or HTTP 5xx. Each attempt re-enters the shared provider throttle;
non-transient 4xx responses fail immediately, and a second transient failure
remains a typed visible error. Query choice stays with the consuming agent.

**M3 blocked-scholarship evidence slice (in review, 2026-08-13):** The
agent-facing OpenAlex serialization bridge now preserves the normalized public
abstract as optional `raw_content`. Consumers may use it as an explicitly
provenance-marked abstract fallback when the publisher page is blocked; it is
not represented as a successful full-page fetch.


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

**v0.9.0 (shipped, 2026-08-12):** Canonical keyless source retrieval.
Adds opt-in Hacker News and arXiv adapters, normalized provenance, and shared
provider pacing with injectable clocks for deterministic tests. The source-level
port preserves the personal repository's Jina Reader support and does not add
the unrelated public `llm-client` package.

**v0.10.0 (shipped, 2026-08-12):** OpenAlex scholarly retrieval. Adds an
opt-in works adapter with keyword, native semantic, and works-only OQL modes;
mode-aware caching; normalized open-access `SearchHit` output; optional bearer
authentication; shared pacing; and an agent-facing tool whose query and mode
are selected by the authorized consuming `llm_client` runtime.

**v0.11.0 (shipped, 2026-08-12):** Reddit practitioner retrieval. Adds an
opt-in OAuth post-search adapter, subreddit scoping, conservative shared pacing,
runtime-only credential handling, and normalized discussion provenance.

**What's next:** prove the agent-driven retrieval MVP below before adding more
providers or pursuing a public package release. Reddit remains a separate
credentialed slice. Embedding execution belongs to `llm_client`; consumer-owned
chunking, similarity policy, and vector storage are not MVP blockers.

---

## The Path

### Agent-Driven Retrieval MVP

**Stage:** internal-product MVP. The release boundary is one reproducible,
inspectable consumer journey, not PyPI publication or a general-purpose
research UI.

**Actor and outcome:** an authorized research agent starts from a natural-language
research goal and produces a provenance-complete evidence bundle by choosing
appropriate retrieval providers, provider modes, and query arguments in context.
The user must not need to hand-author OpenAlex OQL, select every provider, or
repair fetch failures manually.

**Canonical exemplar:**
"What evidence explains why people share conspiracy claims on social media,
what competing explanations exist, and how has the evidence changed since
2020?"

| Starting state | Action | Inspectable result | Evidence step-down | Negative case | Non-claim |
|---|---|---|---|---|---|
| Fresh authorized checkout, configured `llm_client`, no committed secrets | Give the goal to the retrieval-capable agent; it chooses and executes normalized tools | Saved trace plus normalized evidence bundle showing queries, provider/mode choices, hits, fetch/extract methods, failures, and citations | Live traced run → replayable saved artifact → mocked contract tests | Missing credentials or an explicit CAPTCHA fails before unauthorized/live fallback I/O | One passing exemplar does not prove universal site access, exhaustive recall, or production-scale economics |

Current status is `agent retrieval vertical accepted / consumer partially
integrated / stakeholder outcome not yet observed`. OpenAlex keyword probes,
Hacker News, Reddit, fetch/extract, and typed access recovery are already
consumed by Grounded Research. The retained
[M1 receipt](MVP_M1_AGENT_RETRIEVAL_RECEIPT.md) proves that a real agent selected
semantic and OQL modes, constructed both queries from the goal, and received
normalized live evidence. Grounded has not yet adopted that agent/query-plan
seam end to end.

The ownership boundary remains:

- `open_web_retrieval`: validate, execute, pace, normalize, and record search,
  fetch, render, extraction, and provider-operation provenance
- `llm_client`: execute the model/tool loop and retain model/tool observability
- Grounded Research: own the research goal, query-planning policy, evidence
  selection, and final adjudication/report
- `Inside-Success/open_web_retrieval`: remain the public source-overlay
  downstream, pinned to reviewed canonical source snapshots

The backward path is:

```text
inspectable grounded answer
  <- provenance-complete evidence bundle
  <- contextual provider/mode/query decisions
  <- normalized retrieval tools and typed failures
  <- natural-language research goal
```

The first missing boundary is the contextual provider/mode/query decision in an
authentic model-driven run. More adapters, a crawler, and broad anti-bot work do
not enter the critical path until that vertical exposes a specific retrieval
gap.

#### Critical path

| Phase | Outcome and acceptance evidence | Dependency | Status |
|---|---|---|---|
| M0 — canonical substrate | Personal upstream and public downstream expose the same approved Python package; Grounded pins the reviewed downstream revision | Repository ownership and source-port contract | Complete |
| M1 — agent retrieval vertical | On the canonical exemplar, a real `llm_client` run selects at least one appropriate scholarly mode (`semantic` or `oql`) plus any justified complementary provider, constructs valid arguments, and saves a trace and normalized evidence bundle. A malformed query fails visibly; no hard-coded exemplar query counts as success | Existing agent tool surface and authorized model route | Complete — [receipt](MVP_M1_AGENT_RETRIEVAL_RECEIPT.md) |
| M2 — Grounded adoption | Grounded Research consumes the selected agent/query-plan seam and completes collection without bypassing normalized contracts. The trace links goal → tool call → `SearchHit` → fetched/extracted evidence; existing deterministic budgets and provider-specific safety remain enforceable | M1 contract decision | **Next execution frontier** |
| M3 — representative resilience | Run one scholarly case, one current-web case, one practitioner case, and one public access-challenge case. At least three complete with useful evidence; every failure is typed and retained. Missing credentials and explicit CAPTCHA tests prove zero unauthorized HTTP | M2 consumer path; Reddit case only when account use is authorized | In progress — bounded OpenAlex transient retry implemented and mock-verified |
| M4 — clean-machine MVP gate | A fresh clone of the public downstream and Grounded Research installs in new virtual environments, resolves only authorized dependencies, passes credential-free tests, and reproduces one retained live journey from the README/runbook | M3; reviewed downstream source sync | Planned |
| M5 — MVP review | Brian can inspect the trace, evidence bundle, and grounded report and judge whether provider choices and evidence are useful. Continue to pilot only if the result is understandable without repository knowledge and no material failure is silent | M4 artifact | Planned |

#### Planning frontier

| Item | State | Decision or evidence needed | Promotion/replan trigger |
|---|---|---|---|
| Agent selection contract: natural-language goal → typed provider/mode/query calls | `fully_specifiable_now` | Bounded design must choose the smallest seam that preserves OWR validation and Grounded budgets | Adopted M1 design |
| One generic retrieval tool versus several provider-specific tools | `conditional` | Prefer existing provider tools for M1; reconsider only if the live trace shows tool-choice confusion or schema/context overload | M1 failure attributable to tool surface, not model/provider outage |
| OpenAlex keyword/semantic/OQL selection guidance | `fully_specifiable_now` | Preserve mode-specific validation and record the agent's selected mode/query in the trace | M1 authentic receipt |
| arXiv as a second scholarly route | `deliberately_deferred` | OpenAlex already covers the MVP scholarly role; add arXiv only for a demonstrated coverage or full-text gap | Representative scholarly failure with relevant arXiv evidence |
| Reddit live-account execution | `human_decision_required` | Credentials remain runtime-only; a unit/mock path is sufficient until Brian authorizes a live practitioner probe | Explicit live-account authorization for M3 |
| Broader anti-bot or proxy capability | `deliberately_deferred` | CAPTCHA solving, fingerprint evasion, proxy rotation, login, and paywall bypass remain out of scope | A lawful public-page failure blocks the exemplar after current direct/Crawl4AI/Jina routes |
| Embeddings, vector storage, and semantic reranking | `conditional` | Reuse `llm_client` for embedding execution; design consumer policy only if M1–M3 expose ranking as the limiting boundary | Retained trace shows adequate recall but materially poor selection |
| Public package/release | `deliberately_deferred` | MVP is source-installed and SHA-pinned; publication needs a separate ownership and release decision | M5 accepted and a real external consumer requests a release |

#### MVP decision rules

- **Continue** while each phase produces a new authentic consumer capability or
  demonstrates a direct blocker.
- **Change tactics** if two agent attempts fail at the same tool-selection or
  query-construction boundary; inspect the trace before changing the model or
  adding orchestration.
- **Reset the M1 design** if success requires hard-coding the exemplar, hiding
  failures, or moving query intelligence into provider adapters.
- **Stop before promotion** if a clean machine needs Brian's workstation paths,
  the unrelated public `llm-client`, committed credentials, or a private source
  snapshot.
- **Scale to a pilot** only after M5 human review accepts usefulness and the M3
  representative cases show no silent failures.

Non-goals through MVP: recursive crawling, a general scraping framework, proxy
rotation, CAPTCHA solving, login/paywall bypass, a new workflow engine, a vector
database, a broad UI, and support for every adapter in every run.

**Selected next goal:** adopt the accepted M1 agent/query-plan seam in Grounded
Research as the smallest M2 vertical. Preserve Grounded's deterministic budgets
and evidence-selection ownership, then retain one trace linking the natural-
language goal through the contextual OpenAlex call and normalized `SearchHit`
to fetched/extracted evidence. Do not change an existing Grounded dependency or
workflow until its focused consumer checks pass and the impact is raised for
review.

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
| 2026-08-12 | Port HN and arXiv by source, not Git history | The repositories were reviewed independently; a bounded source port makes provenance and accepted contracts explicit without coupling histories. |
| 2026-08-12 | Keep keyless adapters opt-in and share pacing per provider | Existing client defaults and paid-provider behavior stay stable while public-service traffic receives conservative process-wide pacing. |
| 2026-08-12 | Keep OpenAlex query intelligence above the adapter contract | The consuming agent chooses keyword, semantic, or OQL and constructs the query; this library validates, executes, paces, and normalizes it. |
| 2026-08-12 | Limit OQL to ungrouped works queries | Grouped and non-work OQL results cannot safely satisfy the normalized `SearchHit` contract. |
