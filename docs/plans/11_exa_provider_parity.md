# Plan #11: Exa Provider Parity

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** research complete
**Blocks:** faithful Tyler provider execution

---

## Gap

**Current:** Tavily parity is shipped, but Exa parity is still the remaining
open Tyler-required provider gap.

**Target:** add a first-class Exa search adapter to `open_web_retrieval` with
`type="deep"` as the shared default.

**Why:** Tyler explicitly assumed Tavily + Exa provider parity. The live app now
consumes Tavily through the shared provider path; Exa is the remaining provider
gap.

---

## Research Gate

Research was completed in:

- `~/projects/investigations/open_web_retrieval/2026-03-30-exa-provider-research.md`

Decision:

- direct `httpx` adapter
- no contract expansion in this wave
- Exa uses `type="deep"` by default

---

## Pre-Made Decisions

1. Implement Exa search only in this wave.
2. Keep the base `SearchQuery` contract unchanged.
3. Map `SearchQuery.recency_days` to `startPublishedDate`.
4. Preserve Exa-only fields in `SearchHit.raw_payload`.
5. Do not expose `systemPrompt` yet; document that as a follow-on only if a
   real consumer needs it.

---

## Files Affected

- `docs/notebooks/03_exa_provider_parity.ipynb` (create)
- `docs/plans/11_exa_provider_parity.md` (create)
- `docs/ROADMAP.md` (modify)
- `README.md` (modify)
- `CLAUDE.md` (modify if provider inventory changes)
- `pyproject.toml` (modify version)
- `src/open_web_retrieval/models.py` (modify)
- `src/open_web_retrieval/client.py` (modify)
- `src/open_web_retrieval/adapters/exa.py` (create)
- `tests/conftest.py` (modify)
- `tests/test_adapters.py` (modify)
- `tests/test_client.py` (modify)

---

## Success Criteria

### Step 1: Adapter + client wiring

Pass:

- `"exa"` is a valid provider in `SearchQuery`
- `ExaSearchAdapter.search()` returns normalized `SearchHit`
- `OpenWebRetrievalClient(exa_api_key=...)` enables Exa without regressing other providers

Fail:

- Exa requires a new base contract field in this wave
- deep search is not the default

### Step 2: Verification

Pass:

- targeted unit tests pass
- one live Exa smoke passes with the configured shared key
- docs reflect the new provider and the `deep` default

Fail:

- only mocked tests pass
- docs still imply Exa parity is missing

---

## Failure Modes

| Failure Mode | Detection | Response |
|--------------|-----------|----------|
| Exa deep results are too sparse without content fetch | live smoke returns titles only | keep normalized adapter anyway; richer Exa-specific guidance is a separate wave |
| Published-date mapping is unstable | recency tests fail or live smoke rejects the field | keep recency optional and document exact API expectation |
| Exa-specific extras tempt contract bloat | model changes leak `output` or highlight arrays into the base schema | keep all provider extras in `raw_payload` |

---

## Implementation Order

1. Add `exa` to provider contract
2. Implement `adapters/exa.py`
3. Wire `exa_api_key` into client
4. Add tests
5. Run live smoke
6. Update docs and version
