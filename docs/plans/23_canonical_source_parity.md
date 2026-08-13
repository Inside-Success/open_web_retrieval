# Plan #23: Canonical Source Parity

**Status:** Complete
**Type:** downstream source synchronization
**Priority:** High

## Outcome

The tracked `src/open_web_retrieval` package in the public Inside Success
downstream is byte-identical to canonical upstream revision
`42c8e5c67724551019ca9fa9cf74c2e5b31e011f`. Repository metadata, public CI,
and the immutable source pin remain company-owned.

## Compatibility Gate

- Preserve the distribution and import namespace.
- Do not add a private runtime dependency or the unrelated public
  `llm-client` package.
- Run the company suite and canonical upstream suite against the candidate.
- Run Grounded Research's complete suite with the candidate installed.
- Import the ecosystem tool and boundary registration surfaces.
- Do not update a consumer pin or merge if any consumer regression remains.

## Acceptance

- [x] The package-tree digest matches `UPSTREAM.json`.
- [x] Retrieval suites pass without live credentials.
- [x] Grounded Research's complete suite passes against the candidate.
- [x] Ecosystem registration imports succeed.
- [x] Focused lint on the synchronized source reports no new failures.

## Evidence

- Company suite: 262 passed, 1 skipped.
- Canonical upstream suite against the company candidate: 253 passed, 1
  skipped.
- Grounded Research complete suite with imports resolving from the candidate:
  1042 passed, 59 skipped.
- Ecosystem tool and boundary imports resolved from the candidate without
  mutating the persisted registries.
- The synchronized source retains the canonical upstream lint baseline; a
  focused critical-error check is clean. Repository-wide lint and typecheck
  debt are not claimed green.
- GitHub organization and workspace searches found Grounded Research as the
  only executable company consumer; its runtime remains SHA-pinned until a
  separately verified pin update.
