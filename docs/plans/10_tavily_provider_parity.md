# Plan #10: Tavily Provider Parity

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** research complete
**Blocks:** grounded-research Tyler Stage 5 provider parity

---

## Gap

**Current:** `open_web_retrieval` only exposes Brave and SearxNG search adapters.
Tyler-style Stage 5 verification assumes Tavily-class search depth and query execution.

**Target:** add a real Tavily search adapter to the shared client without introducing
multi-provider framework complexity or a second contract surface.

**Why:** Tavily parity is the smallest shared-infra slice that closes the next real
Tyler gap. Keeping this local to `grounded-research` would violate the repo boundary.

---

## Research Gate

Research was completed in:

- `~/projects/investigations/open_web_retrieval/2026-03-30-tavily-provider-research.md`

Decision:

- build a thin direct `httpx` Tavily adapter
- do not borrow LangChain/LlamaIndex wrappers
- do not expand to Exa/Jina in this wave

---

## Pre-Made Decisions

1. Implement Tavily search only in this wave.
2. Use direct `httpx` like the existing Brave/SearxNG adapters.
3. Keep the base search contract unchanged:
   - return normalized `SearchHit`
   - put Tavily-only extras in `raw_payload`
4. Client wiring is config-by-constructor:
   - `OpenWebRetrievalClient(tavily_api_key=...)`
5. No fallback chains or provider-ranking policy in this wave.
6. Live verification uses one real Tavily search call if `TAVILY_API_KEY` is available.

---

## Files Affected

- `docs/notebooks/02_tavily_provider_parity.ipynb` (create)
- `docs/plans/10_tavily_provider_parity.md` (create)
- `docs/ROADMAP.md` (modify)
- `README.md` (modify)
- `src/open_web_retrieval/models.py` (modify)
- `src/open_web_retrieval/client.py` (modify)
- `src/open_web_retrieval/adapters/tavily.py` (create)
- `tests/conftest.py` (modify)
- `tests/test_adapters.py` (modify)
- `tests/test_client.py` (modify)
- `tests/test_tavily_live.py` or equivalent targeted smoke surface if needed

---

## Success Criteria

### Step 1: Contract + plan

Pass:

- Tavily research artifact exists
- notebook planning artifact exists
- provider contract and scope are explicit

Fail:

- adapter implementation begins without a build-vs-borrow decision

### Step 2: Adapter + client wiring

Pass:

- `"tavily"` is a valid provider in `SearchQuery`
- `TavilySearchAdapter.search()` returns normalized `SearchHit`
- `OpenWebRetrievalClient(tavily_api_key=...)` enables Tavily without breaking Brave/SearxNG

Fail:

- provider-specific fields leak into the base contract
- existing adapters regress

### Step 3: Verification

Pass:

- targeted unit tests pass
- one live Tavily smoke passes when `TAVILY_API_KEY` is configured
- docs reflect the new provider and current frontier

Fail:

- tests pass only with mocks and no live request
- docs still describe Brave/SearxNG as the only provider set

---

## Failure Modes

| Failure Mode | Detection | Response |
|--------------|-----------|----------|
| Tavily response shape differs from assumptions | adapter tests fail or live smoke shows missing keys | normalize only required fields and preserve provider extras in `raw_payload` |
| Tavily returns provider-specific rich answer fields that tempt contract bloat | model changes expand beyond `SearchHit` | keep answer/images/follow-up data inside `raw_payload` for this wave |
| Client constructor becomes multi-provider policy soup | `__init__` grows provider-specific branching beyond simple adapter registration | stop at `tavily_api_key` wiring; defer generalized provider selection to a later wave |
| Live smoke fails due to credential/env issues | live test fails but unit tests pass | document env dependency explicitly and keep the unit contract green |

---

## Implementation Order

1. Add Tavily provider to typed model contract
2. Implement `adapters/tavily.py`
3. Wire `tavily_api_key` into `OpenWebRetrievalClient`
4. Add adapter/client tests
5. Run one live Tavily smoke
6. Update README and ROADMAP

---

## Notes

- This is not full Plan #05 closure.
- Exa and Jina remain deferred until Tavily is stable.
- Grounded-research integration is a follow-on application wave, not part of this adapter wave.
