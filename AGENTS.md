# open_web_retrieval - Canonical Repo Instructions

<!-- GENERATED FILE: DO NOT EDIT DIRECTLY -->
<!-- generated_by: scripts/meta/render_agents_md.py -->
<!-- canonical_claude: CLAUDE.md -->
<!-- canonical_relationships: scripts/relationships.yaml -->
<!-- canonical_relationships_sha256: 840b164dcfa4 -->
<!-- sync_check: python scripts/meta/check_agents_sync.py --check -->

This file is a generated Codex-oriented projection of repo governance.
Edit the canonical sources instead of editing this file directly.

Canonical governance sources:
- `CLAUDE.md` — human-readable project rules, workflow, and references
- `scripts/relationships.yaml` — machine-readable ADR, coupling, and required-reading graph

## Purpose

**Version:** 0.8.0
**Last verified:** 2026-03-30

This repo is the shared open-web retrieval boundary.

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

## Operating Rules

This projection keeps the highest-signal rules in always-on Codex context.
For full project structure, detailed terminology, and any rule omitted here,
read `CLAUDE.md` directly.

### Principles

- `open_web_retrieval` is the one canonical place for reusable open-web retrieval primitives.
- Domain repos should consume these primitives before hand-rolling web search, fetch, render, or extraction logic.
- Keep the API intentionally small; avoid speculative abstractions.
- Fail loudly by default. If partial-failure mode is used, it must be explicit.
- Update schema/capability changes and plan references when contracts change.
- **Commit early and often.** Every verified increment gets its own commit.
- **Continue autonomously** until milestone complete or real blocker.

### Workflow

- Edit this file first when changing project policy.
- Keep `AGENTS.md` as a generated mirror (via `render_agents_md.py` in project-meta).
- Do not keep implementation shortcuts that silently alter contract behavior.
- Do not merge local-product UI concerns into this substrate.
- Both clients accept `tool_call_logger: ToolCallLogger | None` for structured tool-call logging. The protocol is defined in `observability.py`. Compatible with `llm_client`'s tool-call logger at runtime (same callable interface).

## Machine-Readable Governance

`scripts/relationships.yaml` is the source of truth for machine-readable governance in this repo: ADR coupling, required-reading edges, and doc-code linkage. This generated file does not inline that graph; it records the canonical path and sync marker, then points operators and validators back to the source graph. Prefer deterministic validators over prompt-only memory when those scripts are available.

## References

| Doc | Purpose |
|-----|---------|
| `docs/REQUIREMENTS.md` | Capabilities, consumers, success criteria |
| `docs/ROADMAP.md` | Version history and future direction |
| `src/open_web_retrieval/models.py` | Schema contract |
| `src/open_web_retrieval/client.py` | Retrieval orchestration |
| `README.md` | Usage examples and observability setup |
