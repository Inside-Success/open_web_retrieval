# Plan #01: Fetch Error Classification

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** research_v3 eval loop (times out retrying permanent 403s)

---

## Gap

**Current:** `SourceFetcher.fetch()` treats all HTTP errors identically — raises
`FetchError` with no classification. The consumer (research_v3 `loop.py`) retries
every exception 3x with backoff. Paywalled sites (Reuters, TheHill, WSJ) always
return 403, wasting ~30s per URL. The loop timed out at 20 minutes on one question.

Additionally, `_extract_with_trafilatura()` silently swallows exceptions (line 58-59),
violating the repo's fail-loud rule.

**Target:** `FetchError` carries a `retryable` field. Consumers check it. Permanent
failures (403, 401, 404) fail fast. The consumer update is in the same slice — the
library change alone does not unblock research_v3.

**Why:** This is the #1 blocker for ROADMAP Phase 2 (research_v3 eval harness).

---

## References Reviewed

- `src/open_web_retrieval/fetch_extract.py:107-125` — current `SourceFetcher.fetch()`
- `src/open_web_retrieval/fetch_extract.py:48-59` — silent trafilatura swallow
- `src/open_web_retrieval/exceptions.py` — `FetchError` (no retryable field)
- `src/open_web_retrieval/client.py:30-65` — `OpenWebRetrievalClient` hardcodes `SourceFetcher`
- `src/open_web_retrieval/models.py` — `FetchRequest`, `FetchedResource`
- `tests/test_fetch_extract.py` — existing fetch tests (this is where new tests go)
- `research_v3/loop.py:91-120` — `_retry_api_call` retries all exceptions generically
- `research_v3/loop.py:48-65` — `LoopRuntime` constructs `SourceFetcher` directly

SOTA research preserved in `docs/SOTA_RESEARCH.md`.

---

## Pre-made Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where does classification live | `FetchError.retryable` field | Consumers check this; backward-compatible (default `True`) |
| How to classify | Status code check in `SourceFetcher.fetch()` | ~20 lines, no new dependencies |
| Transport-level retry (retryhttp) | **Deferred** — internal optimization after gate is proven | Consumer still controls retry policy; library classifies errors |
| Crawl4AI | **Out of scope** — deferred to v0.5 per ROADMAP | Most blocked sites are paywalls, not anti-bot. Prove this first. |
| Consumer update | **In this slice** | Library change alone doesn't unblock — loop.py must check `retryable` |
| Expose config through facade | Yes — `OpenWebRetrievalClient` gets `blocked_domains` param | Prevent consumers from bypassing the facade |
| Fix silent trafilatura swallow | Yes — log warning, don't silently return None | Repo rule: fail loud |

---

## Files Affected

- `src/open_web_retrieval/exceptions.py` (modify — add `retryable` field to `FetchError`)
- `src/open_web_retrieval/fetch_extract.py` (modify — classify HTTP status, blocked domains, fix silent swallow)
- `src/open_web_retrieval/client.py` (modify — pass `blocked_domains` through to `SourceFetcher`)
- `tests/test_fetch_extract.py` (modify — add classification tests)
- `research_v3/loop.py` (modify — check `FetchError.retryable` in `_retry_api_call`)

---

## Plan

### Step 1: Add `retryable` field to `FetchError`

```python
# exceptions.py
class FetchError(OpenWebRetrievalError):
    """Failure while fetching remote content."""
    error_code = "OPEN_WEB_RETRIEVAL_FETCH_ERROR"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, context=context)
        self.retryable = retryable
```

Default `True` preserves backward compatibility — existing callers that don't
check `retryable` behave exactly as before.

### Step 2: Classify HTTP status in `SourceFetcher.fetch()`

```python
# fetch_extract.py
NON_RETRYABLE_STATUS = {401, 403, 404, 410, 451}

# In fetch():
except httpx.HTTPStatusError as exc:
    retryable = exc.response.status_code not in NON_RETRYABLE_STATUS
    raise FetchError(
        f"HTTP {exc.response.status_code}",
        retryable=retryable,
        context={"url": request.url, "status": exc.response.status_code},
    ) from exc
```

Separate `HTTPStatusError` from generic `HTTPError` (timeouts, connection errors)
which remain retryable.

### Step 3: Add `blocked_domains` to `SourceFetcher`

```python
# fetch_extract.py
from urllib.parse import urlparse

class SourceFetcher:
    def __init__(self, *, blocked_domains: set[str] | None = None, ...):
        self._blocked_domains = blocked_domains or set()

    def fetch(self, request):
        domain = urlparse(request.url).netloc.removeprefix("www.")
        if domain in self._blocked_domains:
            raise FetchError(
                f"blocked domain: {domain}",
                retryable=False,
                context={"url": request.url, "domain": domain},
            )
        # ... existing fetch logic
```

### Step 4: Expose `blocked_domains` through `OpenWebRetrievalClient`

```python
# client.py
class OpenWebRetrievalClient:
    def __init__(self, *, blocked_domains: set[str] | None = None, ...):
        ...
        self.fetcher = SourceFetcher(
            timeout_seconds=timeout_seconds,
            blocked_domains=blocked_domains,
        )
```

### Step 5: Fix silent trafilatura swallow

```python
# fetch_extract.py line 58-59
except Exception as exc:
    import logging
    logging.getLogger(__name__).warning("trafilatura extraction failed: %s", exc)
    return None  # fall through to tag-stripping fallback
```

Log the warning. Still falls back to tag stripping, but the failure is visible.

### Step 6: Update consumer (research_v3 `loop.py`)

In `_retry_api_call`, check `retryable` before retrying:

```python
except Exception as exc:
    from open_web_retrieval.exceptions import FetchError
    if isinstance(exc, FetchError) and not exc.retryable:
        logger.info("Skipping non-retryable %s: %s", label, exc)
        raise  # don't retry — let caller handle
    # ... existing retry logic for retryable errors
```

### Step 7: Tests

Add to `tests/test_fetch_extract.py` (existing file, not a new one):

| Test | What It Verifies |
|------|------------------|
| `test_fetch_403_not_retryable` | 403 → `FetchError(retryable=False)` |
| `test_fetch_429_retryable` | 429 → `FetchError(retryable=True)` |
| `test_fetch_500_retryable` | 500 → `FetchError(retryable=True)` |
| `test_fetch_timeout_retryable` | Timeout → `FetchError(retryable=True)` |
| `test_fetch_blocked_domain` | Blocked domain → immediate `FetchError(retryable=False)` |
| `test_fetch_retryable_default_true` | `FetchError()` defaults to `retryable=True` |

---

## Acceptance Criteria

- [x] `FetchError` has `retryable: bool` field (default `True`)
- [x] 401/403/404/410/451 raise with `retryable=False`
- [x] 429/500/502/503/504 raise with `retryable=True`
- [x] Timeouts and connection errors raise with `retryable=True`
- [x] `blocked_domains` parameter on both `SourceFetcher` and `OpenWebRetrievalClient`
- [x] Silent trafilatura swallow replaced with logged warning
- [x] research_v3 `loop.py` checks `FetchError.retryable` — skips permanent failures
- [x] All existing tests pass
- [x] New tests for each classification case
- [ ] **Gate: research_v3 loop completes F1 in <10 minutes** — Deferred; library-side verified via e2e_test.py

---

## Error Taxonomy

| Error | Retryable | Rationale |
|-------|-----------|-----------|
| HTTP 401 Unauthorized | No | Auth failure — retrying won't help |
| HTTP 403 Forbidden | No | Paywall or bot-block — retrying wastes time |
| HTTP 404 Not Found | No | Page doesn't exist |
| HTTP 410 Gone | No | Explicitly removed |
| HTTP 451 Legal | No | Legally blocked |
| HTTP 429 Too Many Requests | Yes | Rate limited — back off and retry |
| HTTP 500 Server Error | Yes | Transient server failure |
| HTTP 502 Bad Gateway | Yes | Proxy/upstream failure |
| HTTP 503 Service Unavailable | Yes | Temporary overload |
| HTTP 504 Gateway Timeout | Yes | Upstream timeout |
| Connection error | Yes | Network transient |
| Timeout | Yes | Network transient |
| Blocked domain | No | Configured skip |

---

## Budget

~1.5 hours total:
- Steps 1-5 (library): ~45 minutes
- Step 6 (consumer): ~15 minutes
- Step 7 (tests): ~30 minutes

---

## Notes

- **No new dependencies.** retryhttp/httpx-retries are deferred as internal
  optimizations. The consumer controls retry policy; the library classifies errors.
- **Crawl4AI is out of scope.** Moved to ROADMAP v0.5. The escalation logic in
  the old plan was contradictory (403 = non-retryable but escalation checked
  `retryable=True`). Don't build it until we prove paywalls aren't the real problem.
- **Transport-level retry is a future optimization.** The consumer (loop.py)
  already has retry logic. Making the library retry internally would duplicate
  that. Classify first, optimize later.

## SOTA Research

Preserved in full — moved to `docs/SOTA_RESEARCH.md` to keep this plan focused.
Key finding: community consensus is that 403 from paywalled news sites should
be treated as permanent failures, not candidates for anti-bot bypass.
