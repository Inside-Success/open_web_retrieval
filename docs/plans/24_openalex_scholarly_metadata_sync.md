# Plan #24: OpenAlex Scholarly Metadata Sync

**Status:** In Progress
**Type:** downstream source synchronization
**Priority:** High

## Outcome

The public Inside Success source-overlay downstream exposes the canonical
upstream's optional descriptive OpenAlex work and venue metadata, so a
clean-machine consumer can distinguish journal-indexed article/review records
without a private Git dependency.

## Provenance and Scope

- Source port: canonical upstream commit
  `ed41f5fb1648f9dd79f798129f5ead84fc0122fc`, included in upstream main
  `644ab93d210b726a4c0be82263fff6fed5f9daf8`.
- Port only the shared `SearchHit` schema, OpenAlex response selection and
  normalization, public export, matching contract test, and capability docs.
- Do not merge histories, alter credentials, or claim OpenAlex metadata proves
  publisher peer review.

## Acceptance

- [ ] `SearchHit` exports optional immutable `ScholarlyWorkMetadata`.
- [ ] OpenAlex selects and normalizes work/venue metadata under mock transport.
- [ ] The full tracked package tree matches upstream `644ab93` exactly.
- [ ] The public test suite passes without credentials.
- [ ] Grounded can install this exact downstream commit in a fresh virtual
  environment and preserve metadata through its normalized search seam.

## Rollback

Revert the source-port commit and restore the prior `UPSTREAM.json` snapshot.
Grounded's scholarly gate remains fail-closed in either state.
