# Plan #22: Public Access-Block Classifier

**Status:** Complete
**Type:** contract extension
**Priority:** High

## Outcome

Consumers that deliberately execute an advisory access alternative can verify
that its returned payload is not another challenge or CAPTCHA by calling the
same classifier used by `SourceFetcher`'s internal fallback ladder.

## Contract

- `classify_access_block(resource)` accepts a normalized `FetchedResource`.
- It returns the existing `FetchBlockReason` value or `None`.
- It performs no I/O and does not alter the existing marker/status behavior.

## Acceptance

- [x] CAPTCHA, challenge, 403, and ordinary content match the internal policy.
- [x] Public export is documented by its type and docstring.
- [x] Focused tests and lint pass; full tests remain green.
