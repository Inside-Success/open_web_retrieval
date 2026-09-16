---
plan_id: "inside-success-open-web-retrieval#12"
dependencies: []
dependencies_reviewed: "2026-09-15"
---
# Plan #12: Multi-Provider Search & Fetch Adapters

**Status:** Planned
**Type:** implementation
**Priority:** Medium
**Blocked By:** None
**Blocks:** research_v3 Phase 5 (provider comparison), prompt_eval provider A/B testing

---

## Gap

**Current:** Two search adapters (Brave, SearxNG) and one fetch/extract pipeline
(httpx + Trafilatura). Every consumer uses the same provider. No way to swap
providers via config or compare quality across providers.

**Target:** Config-driven provider selection for both search and fetch/extract.
Consumers choose provider in their config; open_web_retrieval resolves it and
returns the same typed results regardless. Enables A/B testing, fallback chains,
and provider-specific strengths.

**Why:** Different providers have different strengths:
- Brave: raw results, self-hostable via SearxNG
- Tavily: search + context summarization in one call, reduces LLM work
- Jina AI: fetch → clean markdown conversion (may beat Trafilatura on structured pages)
- Exa: neural/semantic search, good for "find similar" queries
- Others may emerge

Per CLAUDE.md: "Don't wait for duplication; if a capability is general-purpose
or crosses an observability boundary, build it shared."

---

## Pre-Implementation Research (REQUIRED)

**Before writing any adapter code, research whether a multi-provider search
abstraction already exists.** Per CLAUDE.md: "Search before building — the
answer may already exist."

Investigate:
- **LangChain retrievers/tools** — do they already have Tavily/Jina/Exa adapters
  with a common interface? Could we use their adapter code directly (50-200 lines
  extracted) without taking the framework dependency?
- **LlamaIndex data connectors** — same question
- **Tavily SDK** (`tavily-python`) — how thin is it? May be simpler to just wrap
  their SDK than build from scratch
- **Jina Reader API** — is it just a URL prefix (`r.jina.ai/{url}`)? If so, the
  adapter is 20 lines
- **Exa SDK** (`exa-py`) — interface and output format
- **SerpAPI, Serper, SearchAPI** — other search aggregators worth considering?
- **Any existing multi-provider search library** that already normalizes across
  Brave/Tavily/Exa/etc.?

Document findings in an investigation artifact at
`~/projects/investigations/open_web_retrieval/YYYY-MM-DD-multi-provider-research.md`
before proceeding to implementation.

**Gate:** Research complete, findings documented, build-vs-borrow decision made.

---

## Proposed Design (pending research)

## Plan

### New Adapters

Following the existing `adapters/base.py` → `adapters/brave.py` pattern:

- `adapters/tavily.py` — Tavily Search API (search + optional extract)
- `adapters/jina.py` — Jina Reader API (fetch → markdown)
- `adapters/exa.py` — Exa neural search

Each adapter implements the same base interface and returns normalized
`SearchResult` / `FetchedDocument` types.

### Config-Driven Selection

```python
# In consuming project's config
search_provider: "brave"      # or "tavily", "searxng", "exa"
fetch_provider: "default"     # or "jina"
```

`OpenWebRetrievalClient` resolves provider from config:
```python
client = OpenWebRetrievalClient(
    search_provider="tavily",
    fetch_provider="jina",
    # API keys from ~/.secrets/api_keys.env
)
```

### Fallback Chains (future)

```python
search_providers: ["brave", "tavily"]  # try brave first, tavily on failure
```

### Provider-Specific Features

Some providers offer capabilities beyond the base interface:
- Tavily: `include_answer=True` returns a pre-summarized answer
- Exa: `find_similar(url)` for similarity search
- Jina: returns structured markdown with metadata

Expose these as optional kwargs, not base interface changes.

---

## Files Affected

- `src/open_web_retrieval/adapters/tavily.py` (create)
- `src/open_web_retrieval/adapters/jina.py` (create)
- `src/open_web_retrieval/adapters/exa.py` (create)
- `src/open_web_retrieval/client.py` (modify — add provider resolution)
- `tests/test_tavily.py` (create)
- `tests/test_jina.py` (create)
- `tests/test_exa.py` (create)
- `pyproject.toml` (add optional deps: `tavily-python`, `exa-py`)

---

## Implementation Order

1. Research (see above) — build-vs-borrow decision
2. Tavily adapter (most different from Brave, highest value)
3. Jina adapter (clean markdown fetch, may improve extraction quality)
4. Config-driven provider resolution in client.py
5. Exa adapter (neural search, lower priority)
6. Fallback chain support (future, if needed)

---

## Acceptance Criteria

- [ ] Pre-implementation research documented
- [ ] At least 2 new search/fetch providers available
- [ ] Provider selected via config, not code changes
- [ ] Same `SearchResult`/`FetchedDocument` types returned regardless of provider
- [ ] Existing Brave/SearxNG adapters unaffected
- [ ] Tests for each new adapter
- [ ] API keys loaded from `~/.secrets/api_keys.env`

---

## Notes

- Start with Tavily — it's the most commonly used alternative to Brave and
  has a clean SDK
- Jina Reader might be as simple as `f"https://r.jina.ai/{url}"` — verify
  in research phase
- Don't add all providers at once. Each should be independently useful.
- This enables prompt_eval A/B testing: same question, different search
  provider, measure quality difference
