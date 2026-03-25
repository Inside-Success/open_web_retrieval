# Plan #01: Fetch Resilience and Crawl4AI Integration

**Status:** Planned
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** research_v3 eval loop performance (currently times out on paywalled sites)

---

## Gap

**Current:** `SourceFetcher.fetch()` treats all HTTP errors identically — raises `FetchError`
on any 4xx/5xx with no classification. Consumers like research_v3's loop retry 3x on every
failure, wasting ~30s per paywalled site (Reuters, TheHill, WSJ, etc.). The loop timed out
at 20 minutes on a single question because of this.

**Target:** Two-tier fetch with HTTP error classification:
1. **Fast path** (httpx + trafilatura) — for cooperative sites. Classify errors as
   retryable (429/5xx) vs permanent (401/403/404). Return immediately on permanent errors.
2. **Escalation path** (Crawl4AI) — for sites that return 403 due to anti-bot protection.
   Crawl4AI has 3-tier anti-bot detection (HTTP status, short/empty bodies, structural
   HTML markers for Cloudflare/DataDome/PerimeterX).

**Why:** The loop infrastructure works — it found real Palantir contract data across 3 rounds.
But wall-clock time is dominated by futile retries on paywalled sites. This is the #1
blocker for running the eval harness.

---

## References Reviewed

- `src/open_web_retrieval/fetch_extract.py:107-125` — current `SourceFetcher.fetch()`
- `src/open_web_retrieval/exceptions.py` — current `FetchError` (no retryable field)
- `src/open_web_retrieval/models.py` — `FetchRequest`, `FetchedResource` contracts
- Crawl4AI docs: anti-bot detection (3-tier), AsyncWebCrawler API, CrawlResult schema
- Crawl4AI GitHub: 62.5k stars, Apache-2.0, fully self-hostable
- research_v3 loop.py F1 run log (2026-03-24): 403 on reuters.com, thehill.com,
  visualcapitalist.com — each wasted 3 retries x backoff

## SOTA Research (2026-03-24)

| Tool | Verdict |
|------|---------|
| **Crawl4AI** | Best fit — free, OSS, anti-bot detection, Markdown output for LLM |
| Firecrawl | Great cloud API, self-hosted crippled (anti-bot is proprietary) |
| Scrapfly | Best anti-bot, cloud-only, $30-100/mo |
| Tavily | Search API, wrong tool for fetching |
| Jina Reader | Good markdown, explicitly no anti-bot |
| httpx+trafilatura | Current — works for cooperative sites, blind to paywalls |

### Community Research (2026-03-24)

**Crawl4AI real-world findings:**
- 62.5k GitHub stars, actively maintained (v0.8.5), Apache-2.0
- Success rate ~89.7% vs Firecrawl's 95.3% (Bright Data benchmark)
- Anti-bot detection works via 3-tier escalation: HTTP status → proxy rotation → fallback function
- `CrawlResult.crawl_stats` exposes `resolved_by: "direct"|"proxy"|"fallback_fetch"|null`
- **Gotchas:** 100-200MB RAM per browser instance; Playwright dependency; anti-bot bypass rate
  can degrade as Cloudflare updates (FlareSolverr saw 90%→30% within weeks)
- **Key insight from community:** Cloudflare now uses "AI Labyrinth" to redirect bots to
  AI-generated honeypot pages — sophisticated anti-bot is an arms race

**Industry trend (2026):**
- Shift from "httpx + parse" to "browser automation + visual extraction"
- Best practice: use httpx as fast path, escalate to browser only when needed
- "Efficient pattern: LLMs generate scraper code once, run deterministically at scale"
- Our httpx+trafilatura stack is still the recommended "Indie/MVP" approach per Bright Data

**Risk assessment for Crawl4AI integration:**
- LOW: Phase 1 (HTTP classification) — no new deps, immediate value
- MEDIUM: Phase 2 (Crawl4AI) — adds Playwright dependency (~200MB), async migration needed
- Crawl4AI's anti-bot is not magic — Cloudflare-protected paywalled news sites (Reuters, WSJ)
  may still block regardless. The real win is skipping known-permanent 403s, not bypassing them.

**Existing retry libraries (don't hand-roll):**
- `retryhttp` (14 stars, actively maintained) — tenacity-based, retries 429/500/502/503/504,
  supports httpx natively. `pip install retryhttp[httpx]`. Does NOT retry 403 (correct behavior).
- `httpx-retries` — transport-layer retry for httpx. Successor to deprecated `httpx-retry`.
  `RetryTransport` wraps httpx.Client. Configurable status codes and backoff.
- Either of these could replace our hand-rolled retry in loop.py's `_retry_api_call`.

**Crawl4AI deployment concerns:**
- Playwright is NOT optional — `crawl4ai-setup` installs browser binaries (~150MB Chromium)
- 100-200MB RAM per browser instance
- Playwright has known memory leaks in long-running sessions (Microsoft issue #6319, #15400, #29163)
  — must recycle browser contexts periodically (e.g., every 10 pages)
- MemoryAdaptiveDispatcher auto-adjusts concurrency but requires monitoring
- No lightweight httpx-only mode exists

**Revised Phase 1 recommendation:**
Use `retryhttp` or `httpx-retries` instead of hand-rolling HTTP error classification.
Both libraries already classify 403 as non-retryable and handle 429 with backoff.
This reduces Phase 1 from ~50 lines of custom code to ~5 lines of configuration.

Sources:
- [Crawl4AI vs Firecrawl: Detailed Comparison 2026 (Bright Data)](https://brightdata.com/blog/ai/crawl4ai-vs-firecrawl)
- [Crawl4AI Anti-Bot Documentation](https://docs.crawl4ai.com/advanced/anti-bot-and-fallback/)
- [Crawl4AI vs Firecrawl: Full Comparison (CapSolver)](https://www.capsolver.com/blog/AI/crawl4ai-vs-firecrawl)
- [AI Web Scraping 2026 (Morph)](https://www.morphllm.com/ai-web-scraping)
- [Cloudflare AI Labyrinth](https://blog.cloudflare.com/ai-labyrinth/)
- [Best Python HTTP Clients 2026 (Bright Data)](https://brightdata.com/blog/web-data/best-python-http-clients)
- [retryhttp GitHub](https://github.com/austind/retryhttp)
- [httpx-retries GitHub](https://github.com/will-ockmore/httpx-retries)
- [Playwright Memory Issues (Microsoft #6319)](https://github.com/microsoft/playwright/issues/6319)
- [AI Agent Retry Patterns (Fast.io)](https://fast.io/resources/ai-agent-retry-patterns/)
- [Crawl4AI Self-Hosting Guide](https://docs.crawl4ai.com/core/self-hosting/)
- [Crawl4AI Installation](https://docs.crawl4ai.com/core/installation/)

---

## Pre-made Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Keep httpx+trafilatura as default | Yes | Fast, no dependencies, works for most URLs |
| Add Crawl4AI as optional escalation | Yes | Free, OSS, directly solves anti-bot. `pip install crawl4ai[all]` |
| Where does error classification live | `FetchError.retryable` field | Consumers check this; no behavior change for existing code |
| Sync vs async | Keep SourceFetcher sync, add AsyncSourceFetcher for Crawl4AI | Crawl4AI is async-only; don't force sync callers to change |
| Known-blocked domain list | Configurable, not hardcoded | Pass via constructor or env var |

---

## Plan

### Phase 1: HTTP Error Classification (no new dependencies)

**Step 1.1: Add `retryable` field to FetchError**
```python
class FetchError(OpenWebRetrievalError):
    retryable: bool = True
```

**Step 1.2: Classify HTTP status codes in SourceFetcher.fetch()**
```python
NON_RETRYABLE_STATUS = {401, 403, 404, 410, 451}

except httpx.HTTPStatusError as exc:
    retryable = exc.response.status_code not in NON_RETRYABLE_STATUS
    raise FetchError(..., retryable=retryable) from exc
```

**Step 1.3: Add optional blocked_domains parameter**
```python
def __init__(self, *, blocked_domains: set[str] | None = None, ...):
    self._blocked_domains = blocked_domains or set()

def fetch(self, request):
    domain = urlparse(request.url).netloc.removeprefix("www.")
    if domain in self._blocked_domains:
        raise FetchError("blocked domain", retryable=False, ...)
```

**Acceptance criteria (Phase 1):**
- [ ] `FetchError` has `retryable: bool` field
- [ ] 403/401/404 raise with `retryable=False`
- [ ] 429/500/503 raise with `retryable=True`
- [ ] `blocked_domains` parameter skips fetch immediately
- [ ] Existing tests pass (no behavior change for callers that don't check `retryable`)
- [ ] New tests for each status code classification

### Phase 2: Crawl4AI Escalation Backend (optional dependency)

**Step 2.1: Add `crawl4ai` as optional dependency**
```toml
[project.optional-dependencies]
antibот = ["crawl4ai[all]"]
```

**Step 2.2: Add `Crawl4AIFetcher` class**
Async fetcher that wraps `AsyncWebCrawler`. Maps `CrawlResult` to `FetchedResource`.
Uses Crawl4AI's anti-bot detection and stealth Playwright.

**Step 2.3: Add escalation logic to SourceFetcher**
```python
def fetch(self, request):
    try:
        return self._httpx_fetch(request)  # fast path
    except FetchError as exc:
        if not exc.retryable or self._crawl4ai is None:
            raise
        return self._crawl4ai_fetch(request)  # escalation
```

**Acceptance criteria (Phase 2):**
- [ ] `pip install open_web_retrieval[antibot]` installs crawl4ai
- [ ] Crawl4AI backend produces valid `FetchedResource` with provenance
- [ ] Escalation fires on 403 when Crawl4AI is available
- [ ] Without crawl4ai installed, behavior is identical to Phase 1

### Phase 3: Consumer Updates

**Step 3.1: Update research_v3 loop.py**
Check `exc.retryable` in `_retry_api_call` before retrying:
```python
except FetchError as exc:
    if not exc.retryable:
        logger.info("Skipping non-retryable: %s", exc)
        return None
```

**Acceptance criteria (Phase 3):**
- [ ] research_v3 loop skips permanent failures immediately
- [ ] Loop completes F1 question in <10 minutes (was timing out at 20)

---

## Required Tests

### New Tests

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_fetch.py` | `test_403_is_not_retryable` | 403 → FetchError(retryable=False) |
| `tests/test_fetch.py` | `test_429_is_retryable` | 429 → FetchError(retryable=True) |
| `tests/test_fetch.py` | `test_blocked_domain_skips` | Blocked domain → immediate FetchError |
| `tests/test_fetch.py` | `test_escalation_to_crawl4ai` | 403 on httpx → escalation to Crawl4AI |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| All existing open_web_retrieval tests | No behavior change for callers that don't check retryable |

---

## Budget

- Phase 1: ~1 hour (HTTP classification, no new deps)
- Phase 2: ~2 hours (Crawl4AI integration, async adapter)
- Phase 3: ~30 minutes (consumer update)
- **Total: ~3.5 hours**

---

## Notes

- Phase 1 alone solves the immediate problem (no more retrying 403s). Phase 2 adds
  the ability to actually fetch from anti-bot protected sites.
- Crawl4AI is async-only (`AsyncWebCrawler`). The sync `SourceFetcher` can call it
  via `asyncio.run()` or we add a parallel `AsyncSourceFetcher`.
- The root CLAUDE.md principle applies: "Prefer libraries when failures surface in
  their output." Crawl4AI's anti-bot failures surface clearly (CrawlResult.success,
  block detection reason). We can diagnose without reading Crawl4AI internals.
- Community feedback on Crawl4AI needed — check Reddit/Twitter for real-world usage
  reports and gotchas before committing to Phase 2.
