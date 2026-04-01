# Plan #02: Robust Fetch (v0.3)

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #01 (complete)
**Blocks:** Sustained autonomous operation (running 7+ questions without getting banned)

---

## Gap

**Current (v0.2):** Fetch errors are classified but the library has no protection
against overloading hosts or APIs. Running a batch of 7 questions means ~50 fetches
in rapid succession with no delays. The Brave API returns `Retry-After` headers on
429 — we ignore them. No per-host rate limiting means a single search can hammer
one domain with 4 parallel fetches. No metrics means we can't observe fetch behavior.

**Target (v0.3):** The library is polite, observable, and can run unsupervised.
Rate limiting prevents bans. Retry-After is respected. Fetch metrics are available
to consumers for logging and alerting.

**Why:** research_v3 needs to run all 7 golden cases + baselines autonomously.
Without rate limiting, Brave will throttle us and target hosts may ban our IP.

---

## References Reviewed

- `src/open_web_retrieval/fetch_extract.py` — current `SourceFetcher.fetch()`
- `src/open_web_retrieval/adapters/brave.py` — Brave adapter, no rate limiting
- `src/open_web_retrieval/client.py` — `OpenWebRetrievalClient` orchestrator
- `tests/test_fetch_extract.py` — existing test surface (79 tests total)
- SOTA research: rate limiting best practices, Retry-After semantics

---

## Pre-made Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rate limiter implementation | `time.sleep()` based, not async | Library is sync; consumers handle async |
| Rate limit scope | Per-domain, not global | Different hosts have different tolerances |
| Default rate | 2 req/s per domain | Conservative. Configurable. |
| Retry-After scope | Fetch only (not search adapters) | Search adapters handle their own 429s |
| Metrics format | Dataclass with counters, not structured logging | Consumers decide how to log |
| Robots.txt | **Deferred to v0.4** | Adds complexity (need parser, caching). Rate limiting is more urgent. |

---

## Files Affected

- `src/open_web_retrieval/fetch_extract.py` (modify — Retry-After, rate limiting)
- `src/open_web_retrieval/client.py` (modify — expose rate limit config, surface metrics)
- `src/open_web_retrieval/models.py` (modify — add FetchMetrics model)
- `tests/test_fetch_extract.py` (modify — rate limit and Retry-After tests)

---

## Plan

### Step 1: Add FetchMetrics dataclass

```python
# models.py
@dataclass
class FetchMetrics:
    """Counters for fetch operations. Consumers read these for observability."""
    fetched: int = 0
    skipped_blocked: int = 0
    skipped_permanent: int = 0
    retried: int = 0
    failed: int = 0
    total_wait_seconds: float = 0.0
```

Attached to `SourceFetcher` as `self.metrics`. Consumers access via
`fetcher.metrics` or `client.fetcher.metrics`.

### Step 2: Respect Retry-After header on 429

In `SourceFetcher.fetch()`, when catching `HTTPStatusError` with status 429:

```python
except httpx.HTTPStatusError as exc:
    if exc.response.status_code == 429:
        retry_after = exc.response.headers.get("Retry-After")
        wait = _parse_retry_after(retry_after) if retry_after else 5.0
        self.metrics.total_wait_seconds += wait
        time.sleep(wait)
        self.metrics.retried += 1
        # retry once after waiting
        response = self.client.get(request.url, headers=headers, follow_redirects=True)
        response.raise_for_status()
    else:
        retryable = exc.response.status_code not in NON_RETRYABLE_STATUS
        raise FetchError(...)
```

`_parse_retry_after` handles both integer seconds and HTTP-date formats.

### Step 3: Per-domain rate limiting

Add `rate_limit_per_second` param to `SourceFetcher.__init__` (default 2.0).
Track last-request time per domain. Sleep if needed before each fetch.

```python
class SourceFetcher:
    def __init__(self, *, rate_limit_per_second: float = 2.0, ...):
        self._rate_limit = rate_limit_per_second
        self._last_request: dict[str, float] = {}  # domain → timestamp

    def _rate_limit_wait(self, domain: str) -> None:
        if self._rate_limit <= 0:
            return
        now = time.monotonic()
        min_interval = 1.0 / self._rate_limit
        last = self._last_request.get(domain, 0.0)
        wait = max(0.0, min_interval - (now - last))
        if wait > 0:
            time.sleep(wait)
            self.metrics.total_wait_seconds += wait
        self._last_request[domain] = time.monotonic()
```

### Step 4: Expose config through OpenWebRetrievalClient

```python
class OpenWebRetrievalClient:
    def __init__(self, *, rate_limit_per_second: float = 2.0, ...):
        self.fetcher = SourceFetcher(
            ...,
            rate_limit_per_second=rate_limit_per_second,
        )
```

### Step 5: Update metrics on every fetch outcome

In `fetch()`, increment the appropriate counter:
- Success → `metrics.fetched += 1`
- Blocked domain → `metrics.skipped_blocked += 1`
- Permanent error → `metrics.skipped_permanent += 1`
- Retried (429) → `metrics.retried += 1`
- Failed after retry → `metrics.failed += 1`

### Step 6: Tests

Add to `tests/test_fetch_extract.py`:

| Test | What It Verifies |
|------|------------------|
| `test_retry_after_header_respected` | 429 with Retry-After → waits, retries once |
| `test_retry_after_integer_seconds` | Retry-After: 3 → sleeps 3s (use mock) |
| `test_retry_after_missing_uses_default` | 429 without header → sleeps 5s default |
| `test_rate_limit_delays_requests` | 2 rapid fetches to same domain → second waits |
| `test_rate_limit_different_domains_no_delay` | Different domains → no delay |
| `test_rate_limit_disabled_zero` | rate_limit_per_second=0 → no delay |
| `test_metrics_incremented` | Successful fetch → metrics.fetched == 1 |
| `test_metrics_blocked_domain` | Blocked domain → metrics.skipped_blocked == 1 |

---

## Acceptance Criteria

- [x] `FetchMetrics` dataclass exists with 6 counters
- [x] 429 responses respect `Retry-After` header (integer and HTTP-date)
- [x] Per-domain rate limiting with configurable rate (default 2 req/s)
- [x] Rate limit and Retry-After config exposed through `OpenWebRetrievalClient`
- [x] Metrics incremented on every fetch outcome
- [x] All existing tests pass (79 from v0.2)
- [x] 8 new tests for rate limiting, Retry-After, and metrics
- [ ] **Gate: 7-question eval batch completes without 429 errors from Brave** — Deferred; library-side verified via e2e_test.py

---

## Budget

~2 hours:
- Steps 1-2 (Retry-After): ~30 minutes
- Steps 3-4 (rate limiting): ~45 minutes
- Steps 5-6 (metrics, tests): ~45 minutes
