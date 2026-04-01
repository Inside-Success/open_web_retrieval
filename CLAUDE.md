# open_web_retrieval - Canonical Repo Instructions

**Version:** 0.8.0
**Last verified:** 2026-04-01

This repo is the shared open-web retrieval boundary.

## Purpose

- Search: Brave, SearxNG, Tavily, and Exa adapters in a normalized contract.
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

## Principles

- `open_web_retrieval` is the one canonical place for reusable open-web retrieval primitives.
- Domain repos should consume these primitives before hand-rolling web search, fetch, render, or extraction logic.
- Keep the API intentionally small; avoid speculative abstractions.
- Fail loudly by default. If partial-failure mode is used, it must be explicit.
- Update schema/capability changes and plan references when contracts change.
- **Commit early and often.** Every verified increment gets its own commit.
- **Continue autonomously** until milestone complete or real blocker.

## Workflow

- Edit this file first when changing project policy.
- Keep `AGENTS.md` as a generated mirror (via `scripts/meta/render_agents_md.py`).
- Do not keep implementation shortcuts that silently alter contract behavior.
- Do not merge local-product UI concerns into this substrate.
- Both clients accept `tool_call_logger: ToolCallLogger | None` for structured tool-call logging. The protocol is defined in `observability.py`. Compatible with `llm_client`'s tool-call logger at runtime (same callable interface).
- Treat `docs/ops/CAPABILITY_DECOMPOSITION.md` as the repo-local source of
  record for shared capability ownership and boundary posture.

## Dependencies

- **Required:** `httpx`, `pydantic`
- **Optional:** `trafilatura` (`[extract]`), `playwright` (`[render]`), `crawl4ai` (`[antibot]`), `llm_client` (`[tools]` -- provides `@tool` decorator for search adapter registration)
- **Observability:** `tool_call_logger` is a `Protocol`-based callable. When `llm_client` is installed, its tool-call logger is directly compatible.

## References

| Doc | Purpose |
|-----|---------|
| `docs/REQUIREMENTS.md` | Capabilities, consumers, success criteria |
| `docs/ROADMAP.md` | Version history and future direction |
| `docs/ops/CAPABILITY_DECOMPOSITION.md` | Repo-local ownership ledger for the shared retrieval layer |
| `docs/plans/CLAUDE.md` | Plan index and rollout status contract |
| `src/open_web_retrieval/models.py` | Schema contract |
| `src/open_web_retrieval/client.py` | Retrieval orchestration |
| `README.md` | Usage examples and observability setup |
