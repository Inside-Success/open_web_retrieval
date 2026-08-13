# Plan #21: Typed Access Alternatives

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** agent-visible recovery from terminal access blocks

## Outcome

When a fetch terminates with an access denial, challenge, or CAPTCHA, its
`FetchError` exposes deterministic, typed alternatives when a known official
API/raw route or the existing hosted-reader seam applies. Alternatives are
advisory and never executed automatically.

Canonical example: a blocked Hacker News item URL suggests the official
Firebase item endpoint; a caller can inspect provider, route, requirements,
rationale, original URL, and `automatic=False` before choosing a new request.

## Contract

- `AccessAlternative` is a frozen Pydantic public model.
- `suggest_access_alternatives(url, block_reason)` is pure and performs no I/O.
- Supported deterministic mappings: arXiv API, Hacker News Firebase API,
  Reddit OAuth API, GitHub raw/issues API, and Jina Reader.
- Credential-bearing URLs produce no alternatives. Jina is not suggested for
  CAPTCHA outcomes or URLs containing query parameters, and known mappings
  retain only the query values required to identify the public resource.
- Unknown URLs return no official mapping; non-CAPTCHA clean public URLs may
  still expose the existing Jina reader option.
- `FetchError.alternatives` and `FetchError.context["alternatives"]` contain the
  same records for typed and JSON-oriented consumers.

## Acceptance

- [x] Known URLs normalize to exact provenance-preserving routes.
- [x] Unknown, credential-bearing, and CAPTCHA cases fail closed as specified.
- [x] A mocked blocked fetch proves no alternative HTTP request occurs.
- [x] Existing callers that only inspect `FetchError` remain compatible.
- [x] Public exports and README document advisory behavior.
- [x] Focused tests/lint and full tests pass.
