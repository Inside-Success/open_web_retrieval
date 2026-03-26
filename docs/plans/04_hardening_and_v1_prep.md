# Plan #04: Hardening and v1.0 Prep

**Status:** Complete
**Type:** maintenance + governance
**Priority:** Medium
**Blocked By:** Plans #01-03 (all complete)
**Blocks:** v1.0 shareable library readiness

---

## Gap

**Current:** The library has all v0.2-v0.4 features shipped (98 tests) but the
surrounding infrastructure doesn't match the code quality:
- README is stale (describes v0.1 only)
- No CI — tests only run locally
- pyproject.toml says 0.1.0 despite v0.4 features
- No py.typed marker for downstream type checking
- Brave error messages don't distinguish invalid key from rate limiting
- ROADMAP has stale v0.2/v0.3 step tables for completed work

**Target:** Clean, professional library ready for external use. README documents
actual capabilities. CI catches regressions. Version reflects reality.

---

## Pre-made Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Version bump | 0.4.0 | Reflects feature state. Not 1.0 — that's a ROADMAP Phase 4 milestone. |
| CI platform | GitHub Actions | Already used in project-meta. Simple matrix: py3.10, py3.12. |
| README scope | Quickstart + feature table + API examples | Not exhaustive docs — that's what docs/ is for. |
| py.typed | Yes | Zero cost, enables mypy for consumers. |
| Robots.txt | Defer | Adds complexity (parser, caching). Not blocking any consumer. |

---

## Plan

### Phase 1: Hardening (code quality)

**Step 1.1: Improve Brave API error messages**
When Brave returns 401, the error should say "invalid API key" not generic "fetch failed".
When Brave returns 429, include Retry-After value in the error message.

**Step 1.2: Add py.typed marker**
Create empty `src/open_web_retrieval/py.typed` file.

**Step 1.3: Pin trafilatura version floor**
Change `trafilatura>=1.12` to `trafilatura>=1.12,<3` in pyproject.toml to prevent
breaking changes from trafilatura major versions.

**Step 1.4: Bump version to 0.4.0**
Update pyproject.toml version field.

### Phase 2: README rewrite

**Step 2.1: Rewrite README.md with current capabilities**
- Feature table showing what's shipped
- Quickstart with code examples (search, fetch, extract)
- Show markdown output and metadata
- Show error classification and blocked domains
- Installation options (base, extract, render)
- Link to docs/ for details

### Phase 3: CI and governance

**Step 3.1: Add GitHub Actions workflow**
`.github/workflows/test.yml`:
- Trigger on push to main and PRs
- Matrix: Python 3.10, 3.12
- Steps: install, install trafilatura, pytest
- No deployment — just test validation

**Step 3.2: Update ROADMAP.md**
- Clean up stale step tables for completed versions
- Add v0.4.1 (this plan) as "Hardening"
- Update decision log

**Step 3.3: Update CLAUDE.md**
- Add CI command
- Update "last verified" date
- Reflect current module state

---

## Acceptance Criteria

- [x] Brave 401 error says "invalid API key"
- [x] py.typed marker exists
- [x] trafilatura version pinned with upper bound
- [x] pyproject.toml version = 0.4.0
- [x] README documents all v0.2-v0.4 features with code examples
- [x] GitHub Actions workflow runs tests on push
- [x] ROADMAP reflects current state
- [x] CLAUDE.md reflects current state
- [x] All 98+ tests pass
- [ ] `git push` triggers CI (verify after push)

---

## Budget

~1.5 hours total.
