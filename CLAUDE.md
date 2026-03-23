# open_web_retrieval - Canonical Repo Instructions

This repo is the shared open-web retrieval boundary.

## Purpose

- Search: Brave and SearxNG adapters in a normalized contract.
- Fetch: `httpx` direct fetch with constrained bytes.
- Render: optional Playwright-based fallback when direct fetch is insufficient.
- Extract: normalized extraction metadata with primary Trafilatura path.
- Provenance: every operation records provider, URL lineage, and fetch/extract method.

## Canonical Rules

- `open_web_retrieval` is the one canonical place for reusable open-web retrieval
  primitives.
- Domain repos should consume these primitives before hand-rolling web search,
  fetch, render, or extraction logic.
- Keep the API intentionally small in v0; avoid speculative abstractions.
- Fail loudly by default. If partial-failure mode is used, it must be explicit.
- Update schema/capability changes and plan references when contracts change.

## Mandatory Reading

- `docs/` for package contract and operation notes.
- `src/open_web_retrieval/models.py` for schema contract.
- `src/open_web_retrieval/client.py` for retrieval orchestration.

## Work-in-scope

- v0 provider support: Brave, SearxNG, direct HTTP fetch, optional Playwright
  render fallback, Trafilatura extraction when available.
- Optional future slices should be added as explicit migrations in
  `project-meta/docs/plans` and reflected in governance linkage.

## Maintenance

- Edit this file first.
- Keep `AGENTS.md` as a generated mirror.
- Do not keep implementation shortcuts that silently alter contract behavior.
- Do not merge local-product UI concerns into this substrate.
