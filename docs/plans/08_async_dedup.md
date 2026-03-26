# Plan #08: Async/Sync Deduplication

**Status:** Planned
**Type:** refactor
**Priority:** High
**Blocked By:** Plan #07 (review fixes)

---

## Gap

**Current:** ~920 lines duplicated between sync and async code paths. Every bug fix
must be made in two places. Observability ceremony (~15 lines per emit_tool_call)
is copy-pasted 10+ times across both files.

**Target:** Single source of truth for business logic. Sync wraps async (or shared
functions extracted). Observability is a decorator or context manager, not inline.

---

## Pre-made Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Which is canonical — sync or async? | **Async is canonical** | httpx is async-first. Sync wraps via `_run_async()`. |
| How does sync call async? | `asyncio.run()` with thread fallback | Already proven in `_run_async()` helper |
| Observability pattern | **Context manager** | `with _observe("fetch", ...) as obs:` emits started/succeeded/failed |
| Keep SourceFetcher API? | Yes — thin sync wrapper | Consumers don't change their code |

---

## Plan

### Phase 1: Extract shared business logic (~30 min)

Create `src/open_web_retrieval/_core.py` with pure functions:
- `classify_http_error(status_code: int) -> bool` (retryable?)
- `check_blocked_domain(url: str, blocked: set[str]) -> str | None`
- `parse_retry_after(header: str) -> float`
- `looks_like_js_shell(html_bytes: bytes, text: str) -> bool`
- `extract_embedded_json(html_bytes: bytes) -> str | None`
- `has_empty_mount_point(html_bytes: bytes) -> bool`
- `has_noscript_warning(html_bytes: bytes) -> bool`

These are already in `fetch_extract.py` as module-level functions. Move them to
`_core.py` and import from there in both sync and async.

### Phase 2: Observability context manager (~20 min)

Create a context manager that handles the emit_tool_call ceremony:

```python
@contextlib.contextmanager
def observe(logger, tool_name, operation, **kwargs):
    call_id = make_tool_call_id()
    started = utc_now_iso()
    started_mono = time.monotonic()
    emit_tool_call(logger, call_id=call_id, status="started", ...)
    try:
        yield ObserveContext(call_id=call_id, started=started, ...)
        emit_tool_call(logger, call_id=call_id, status="succeeded", ...)
    except Exception as exc:
        emit_tool_call(logger, call_id=call_id, status="failed", ...)
        raise
```

This replaces ~150 lines of inline emit_tool_call blocks per file.

### Phase 3: Make async canonical (~45 min)

Rewrite `async_fetch.py` as the canonical implementation with all business logic.
Then make `fetch_extract.py`'s `SourceFetcher` a thin sync wrapper:

```python
class SourceFetcher:
    def __init__(self, **kwargs):
        self._async = AsyncSourceFetcher(**kwargs)

    def fetch(self, request):
        return _run_async(self._async.fetch(request))

    def extract(self, resource):
        return self._async.extract(resource)  # extraction is CPU, not async

    def close(self):
        _run_async(self._async.close())
```

Same for `OpenWebRetrievalClient` wrapping `AsyncOpenWebRetrievalClient`.

### Phase 4: Verify and clean up (~20 min)

- Run all 143+ tests
- Delete duplicated code from old `fetch_extract.py`
- Verify sync API is identical (same return types, same exceptions)
- Update imports in `__init__.py`

---

## Acceptance Criteria

- [ ] `_core.py` contains all shared pure functions
- [ ] Observability uses context manager pattern (not inline)
- [ ] `AsyncSourceFetcher` is the canonical implementation
- [ ] `SourceFetcher` is a thin sync wrapper (~50 lines, not ~965)
- [ ] All existing tests pass without modification
- [ ] No duplicated business logic between sync and async
- [ ] Total LOC reduced by ~30%

---

## Risks

- `asyncio.run()` inside sync code can conflict with existing event loops
  (already handled by `_run_async` thread fallback)
- Extraction is CPU-bound — keeping it sync inside the async wrapper is correct
- Search adapters are sync — calling them from async requires executor or inline
  (they're fast, inline is fine)

---

## Budget

~2 hours total.
