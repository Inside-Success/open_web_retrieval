# Plan #09: grounded-research Retrieval Follow-Ups

**Status:** Planned
**Type:** implementation
**Priority:** High
**Blocked By:** None

---

## Gap

**Current:** `open_web_retrieval` is feature-complete for current consumers, and
Wave 0 tool-call observability is landed. But `grounded-research` surfaced two
reusable follow-ups during dense UBI benchmark work:

- retrieval quality improved materially when PDF/local parsing and fallback
  behavior improved
- tool-call logs now exist, but diagnosing weak domains/extractors/fallback
  paths still requires manual inspection

**Target:** one shared follow-up slice that improves:

1. fallback robustness for hard pages/PDFs and blocked fetches,
2. retrieval diagnostics on top of the new `tool_call_logger` surface,
3. consistency of `trace_id`/`task` propagation across shared entrypoints.

**Why:** these gains are reusable across every consumer. They should not be
re-solved inside application repos.

---

## References Reviewed

- `CLAUDE.md` — repo purpose, maintenance guidance, observability boundary
- `docs/ROADMAP.md` — shipped scope and current v1.0 posture
- `docs/REQUIREMENTS.md` — consumer expectations and success criteria
- `README.md` — current `tool_call_logger` contract and public positioning
- `src/open_web_retrieval/observability.py` — Wave 0 logging surface
- `src/open_web_retrieval/client.py` — shared search orchestration
- `src/open_web_retrieval/fetch_extract.py` — fetch/extract/fallback boundary
- `~/projects/grounded-research/docs/TECH_DEBT.md` — downstream retrieval/runtime findings
- `~/projects/grounded-research/output/ubi_wave2_prefetch_collection/collected_bundle.json` — concrete benchmark trigger artifact

---

## Pre-Made Decisions

1. Do not expand to new providers first; improve the current Brave/SearxNG +
   fetch/extract stack first.
2. Keep the public API small. Prefer better defaults and better diagnostics over
   new abstraction layers.
3. Use the existing `tool_call_logger` contract; do not invent a second
   observability interface.
4. Improve fallback ordering before adding more fallback types.
5. Keep project-specific ranking logic out of this repo unless it is clearly
   reusable across consumers.

---

## Files Affected

- `docs/notebooks/01_grounded_research_followups.ipynb` (create)
- `docs/plans/09_grounded_research_followups.md` (create)
- `docs/ROADMAP.md` (modify)
- `README.md` (modify if contract/usage guidance changes)
- `src/open_web_retrieval/observability.py` (modify)
- `src/open_web_retrieval/client.py` (modify)
- `src/open_web_retrieval/fetch_extract.py` (modify)
- `src/open_web_retrieval/async_fetch.py` (modify if parity required)
- `tests/test_client.py` (modify)
- `tests/test_fetch_extract.py` (modify)
- async parity tests as needed

---

## Plan

### Step 1: Tighten fallback behavior for hard pages and PDFs

- inspect current blocked-page/PDF failure paths
- make fallback ordering explicit and testable
- ensure failed primary paths and successful fallback paths are both visible in
  shared logs

### Step 2: Improve retrieval diagnostics on the existing tool-call surface

- make it easier to answer which provider/domain/extractor failed most
- make successful fallback paths distinguishable from primary fetch success
- keep payloads compact and query-friendly

### Step 3: Normalize trace/task propagation across public entrypoints

- verify search/fetch/extract entrypoints all accept and preserve `trace_id`
  and `task`
- close any gaps so consumers get observability by default when they pass those
  values once

### Step 4: Verify against downstream-triggered questions

- use the grounded-research-triggered retrieval questions as the acceptance
  surface:
  - which domains/pages failed?
  - which fallback path saved them?
  - did PDF-heavy evidence quality improve?

---

## Acceptance Criteria

- [ ] Hard-page and PDF fallback order is explicit and covered by tests
- [ ] Shared logs can answer provider/domain/extractor failure questions
- [ ] `trace_id` and `task` propagate consistently across shared entrypoints
- [ ] Existing retrieval API remains small and consumer-facing behavior stays stable

---

## Failure Modes

| Failure Mode | Detection | Response |
|--------------|-----------|----------|
| Fallback robustness improves success rate but makes behavior opaque | higher success, but logs cannot distinguish primary vs fallback path | split success metrics by path and log fallback provenance explicitly |
| Better diagnostics bloat payloads or degrade hot paths | observability rows get large or tests show perf/size regressions | keep metrics compact and summarize instead of storing raw payloads |
| Trace/task propagation is fixed in sync paths but not async | async tests disagree with sync logs | require parity tests before closing the plan |

---

## Notes

- This is a shared-quality follow-up, not a new expansion program.
- If Step 1 alone closes the downstream pain, keep Steps 2–3 narrow.
