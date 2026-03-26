# open_web_retrieval - Canonical Repo Instructions

**Version:** 0.6.0
**Last verified:** 2026-03-26

This repo is the shared open-web retrieval boundary.

## Purpose

- Search: Brave and SearxNG adapters in a normalized contract.
- Fetch: `httpx` direct fetch with error classification, blocked domains, per-domain rate limiting, Retry-After.
- Render: optional Playwright-based fallback when direct fetch is insufficient.
- Anti-bot: optional Crawl4AI escalation on 403 (`enable_antibot=True`).
- SPA detection: auto-render JS shells via Playwright when extraction produces garbage.
- Extract: text and markdown output via Trafilatura, with title/author/date/sitename metadata.
- Provenance: every operation records provider, URL lineage, and fetch/extract method.

## Commands

```bash
make test              # Run all tests
make test-verbose      # Run tests with verbose output
make lint              # Run ruff linter
make typecheck         # Run mypy type checking
make install           # Install base only
make install-extract   # Install with trafilatura
make install-all       # Install with all optional deps
make help              # Show all targets
```

## CI

GitHub Actions runs on push to main and PRs. Matrix: Python 3.10, 3.12.
Workflow: `.github/workflows/test.yml`

## Canonical Rules

- `open_web_retrieval` is the one canonical place for reusable open-web retrieval primitives.
- Domain repos should consume these primitives before hand-rolling web search, fetch, render, or extraction logic.
- Keep the API intentionally small; avoid speculative abstractions.
- Fail loudly by default. If partial-failure mode is used, it must be explicit.
- Update schema/capability changes and plan references when contracts change.
- **Commit early and often.** Every verified increment gets its own commit.
- **Continue autonomously** until milestone complete or real blocker.

## Mandatory Reading

- `docs/REQUIREMENTS.md` — capabilities, consumers, success criteria
- `docs/ROADMAP.md` — version history and future direction
- `src/open_web_retrieval/models.py` — schema contract
- `src/open_web_retrieval/client.py` — retrieval orchestration

## Maintenance

- Edit this file first.
- Keep `AGENTS.md` as a generated mirror.
- Do not keep implementation shortcuts that silently alter contract behavior.
- Do not merge local-product UI concerns into this substrate.
