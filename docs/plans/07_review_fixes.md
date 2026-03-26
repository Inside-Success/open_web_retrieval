# Plan #07: Review Fixes — Docs, Architecture, Code Smells

**Status:** Planned
**Type:** maintenance
**Priority:** High
**Blocked By:** None

---

## Gap

Strategic review found 12 issues across docs, code, and architecture. This plan
fixes everything except the sync/async duplication (separate plan).

---

## Steps

### A. Documentation Fixes

**A1. README wrong e2e path**
- README says `python tests/fixtures/e2e_test.py` → change to `python scripts/e2e_test.py`

**A2. REQUIREMENTS.md self-contradiction on anti-bot**
- Line ~140 says "does NOT own anti-bot bypass" but library now has `enable_antibot`
- Fix: update boundaries section to reflect v0.5 reality

**A3. REQUIREMENTS.md stale "Priority Order" section**
- Lists what to build next but everything is built
- Fix: remove or replace with "All priorities shipped. See ROADMAP.md for history."

**A4. ROADMAP stale v0.5 step table**
- Completed versions should be collapsed summaries, not full step tables
- Fix: collapse v0.5 steps like v0.2-v0.4 were collapsed

**A5. ROADMAP SOTA table stale retryhttp reference**
- Says "Use in v0.2 instead of hand-rolling" but v0.2 hand-rolled
- Fix: update to "Evaluated, deferred — hand-rolled classification simpler for our needs"

**A6. Generate AGENTS.md**
- CLAUDE.md says "Keep AGENTS.md as a generated mirror" but file doesn't exist
- Fix: create AGENTS.md mirroring CLAUDE.md

**A7. Document tool_call_logger / llm_client dependency**
- No documentation for `tool_call_logger` param or its llm_client runtime requirement
- Fix: add section to README and CLAUDE.md

### B. Code Fixes

**B1. User-agent hardcoded to 0.4 in 3 places**
- `models.py:84`, `fetch_extract.py:365`, `async_fetch.py:55`
- Fix: create `__version__` constant, derive user-agent from it
- Single source: read from `importlib.metadata` or define in `__init__.py`

**B2. KNOWN_BLOCKED_DOMAINS force-merged**
- `fetch_extract.py:396`: `self._blocked_domains = (blocked_domains or set()) | KNOWN_BLOCKED_DOMAINS`
- Consumer can't unblock reuters.com even if they want to
- Fix: make KNOWN_BLOCKED_DOMAINS the default for `blocked_domains` param, not force-merged
- `blocked_domains: set[str] | None = None` → if None, use KNOWN_BLOCKED_DOMAINS; if explicit set provided, use that set only

**B3. Silent ModuleNotFoundError in trafilatura import**
- `fetch_extract.py:147-148`: returns empty with no log
- Fix: add `logger.info("trafilatura not installed — extraction will use fallback. Install with: pip install open_web_retrieval[extract]")`
- Same in `async_fetch.py`

**B4. Cache TOCTOU race**
- `cache.py:95-98`: `exists()` check outside lock
- Fix: remove `exists()` check, try read inside lock, catch `FileNotFoundError` as miss

**B5. SearxNG httpx.HTTPError response access**
- `searxng.py:70`: accesses `exc.response` on `HTTPError` which may not have it
- Fix: catch `HTTPStatusError` specifically (like brave.py does)

**B6. models.py stale comment**
- `auto_rendered` field has comment fragment from `escalated` field
- Fix: clean up comment

**B7. client.py dummy FetchRequest(url="")**
- `client.py:269`: creates template with empty URL
- Fix: only use template fields (render_mode, user_agent, max_bytes), not the URL

### C. Architecture (code smell only, no async refactor)

**C1. Log unchecked plan gates**
- Plans 01-03 have unchecked "real-world verification" gates that won't be checked
- Fix: mark as "Deferred — verified via e2e_test.py" or similar

---

## Acceptance Criteria

- [ ] README e2e path corrected
- [ ] REQUIREMENTS.md boundaries updated, stale priorities removed
- [ ] ROADMAP v0.5 steps collapsed, SOTA table updated
- [ ] AGENTS.md exists
- [ ] tool_call_logger documented
- [ ] User-agent derived from single version constant
- [ ] blocked_domains default-not-force pattern
- [ ] trafilatura ModuleNotFoundError logged
- [ ] Cache TOCTOU fixed
- [ ] SearxNG error handling fixed
- [ ] Stale comments cleaned
- [ ] All 143 tests pass
