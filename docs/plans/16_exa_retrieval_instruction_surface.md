# Plan #16: Exa Retrieval Instruction Surface

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #15 complete
**Blocks:** full generic Exa control parity for consumers that need source-preference guidance

---

## Gap

**Current:** `SearchQuery` now exposes shared controls for depth, detail,
detail budget, corpus, and domain filters. Exa still lacks one important
consumer-expressive surface: a first-class retrieval-instruction field that can
map to Exa's `systemPrompt`.

**Target:** add a small, typed, generic retrieval-instruction field to
`SearchQuery`, honor it in the Exa adapter, and fail loud on providers that do
not support it.

**Why:** this is not Tyler-specific. Multiple consumers may need provider-level
guidance like "prefer official evaluations" or "prioritize peer-reviewed
research" without encoding that only in the query text. The missing capability
is a shared contract gap, not a local app concern.

---

## Pre-Made Decisions

1. Add one generic field only:
   - `retrieval_instruction: str | None`

2. This field is **not** a free-form provider options bag.
   It is a single optional instruction string for ranking/retrieval guidance.

3. Exa maps `retrieval_instruction` to request-body `systemPrompt`.

4. Tavily, Brave, and SearxNG do not silently ignore this field.
   If a caller sets `retrieval_instruction` for an unsupported provider, fail
   loud with `CapabilityNotSupportedError`.

5. The field remains optional and non-breaking for existing callers.

6. This wave does not add multiple provider-specific instruction fields.
   If future providers need similar semantics, they should reuse the same
   generic field where possible.

---

## Files Affected

- `docs/plans/16_exa_retrieval_instruction_surface.md`
- `docs/notebooks/05_exa_retrieval_instruction_surface.ipynb`
- `docs/plans/CLAUDE.md`
- `docs/ROADMAP.md`
- `README.md`
- `src/open_web_retrieval/models.py`
- `src/open_web_retrieval/adapters/exa.py`
- `src/open_web_retrieval/adapters/tavily.py`
- `src/open_web_retrieval/adapters/brave.py`
- `src/open_web_retrieval/adapters/searxng.py`
- `tests/test_adapters.py`
- `tests/test_models.py`

---

## Success Criteria

### Step 1: Contract

Pass:

- `SearchQuery` exposes one optional typed `retrieval_instruction` field
- existing callers remain valid without setting it

Fail:

- contract adds a provider-specific field name like `exa_system_prompt`
- contract grows an untyped options bag

### Step 2: Adapter behavior

Pass:

- Exa request bodies include `systemPrompt` when the field is set
- unsupported providers fail loud if the field is set

Fail:

- unsupported providers silently ignore the field
- Exa support exists only in docs/tests, not request payloads

### Step 3: Verification

Pass:

- adapter tests prove Exa request-body propagation
- adapter tests prove fail-loud behavior for unsupported providers

Fail:

- tests only cover the happy path
- no negative-path coverage exists

---

## Required Tests

| Test / Check | What It Verifies |
|--------------|------------------|
| `pytest -q tests/test_adapters.py` | Exa honors `retrieval_instruction`; unsupported providers fail loud |
| `pytest -q tests/test_models.py` | contract remains valid/non-breaking |
| notebook JSON parse | planning artifact is valid |

---

## Failure Modes

1. Overfitting the contract to Exa instead of keeping it consumer-generic
2. Letting unsupported providers ignore the field silently
3. Treating query text and retrieval instruction as interchangeable
4. Adding the field without docs/tests that explain support boundaries

---

## Exit Condition

This wave is complete when:

- the shared contract exposes one generic retrieval-instruction field,
- Exa maps it to `systemPrompt`,
- unsupported providers fail loud,
- and the repo docs describe it as generic shared capability.

## Completed 2026-04-08

- added `SearchQuery.retrieval_instruction` as one generic retrieval-guidance field
- mapped that field to Exa request-body `systemPrompt`
- made Brave, SearxNG, and Tavily fail loud if callers set the field
- added adapter tests for Exa propagation and unsupported-provider rejection

## Verification Evidence

- `python -m pytest tests/test_adapters.py tests/test_models.py tests/test_client.py -q`
  - `71 passed`
- `python -m json.tool docs/notebooks/05_exa_retrieval_instruction_surface.ipynb >/dev/null`
