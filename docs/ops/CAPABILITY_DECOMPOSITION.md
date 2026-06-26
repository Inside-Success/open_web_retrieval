# Capability Decomposition

Last updated: 2026-04-01

## Purpose

This document is the repo-local source of record for what
`open_web_retrieval` owns as shared retrieval infrastructure, what it
intentionally exports to consumer repos, and what it should not quietly absorb.

Use this together with:

- [`../plans/13_governed-baseline-and-capability-ownership-rollout.md`](../plans/13_governed-baseline-and-capability-ownership-rollout.md)
- [`../REQUIREMENTS.md`](../REQUIREMENTS.md)
- [`../ROADMAP.md`](../ROADMAP.md)
- [`../../README.md`](../../README.md)
- [`../../CLAUDE.md`](../../CLAUDE.md)

## Role

`open_web_retrieval` is the shared open-web retrieval substrate for the
ecosystem.

It owns:

- normalized search adapters and search result contracts
- shared fetch, render-escalation, and extraction primitives
- provenance and fetch/extract method tracking
- reusable resilience policies such as blocked domains, retry classification,
  rate limiting, and cache-backed retrieval helpers
- shared retrieval observability emission at the tool boundary

It does not own:

- project-specific query generation, ranking, or post-retrieval analysis
- generic LLM execution, model routing, or observability storage
- recursive crawling or broad scraping-framework behavior
- cross-repo governance policy or capability registry rules

Those stay in consuming projects, `llm_client`, or `project-meta`.

## Capability Ledger

| Capability | Current owner | Intended owner | Class | Posture | Notes |
|---|---|---|---|---|---|
| Search/fetch/extract provider adapters, normalized retrieval contracts, provenance, and resilience primitives | `open_web_retrieval` | `open_web_retrieval` | shared infrastructure | no move planned | This is the primary shared capability exported by the repo. |
| Optional render and anti-bot escalation backends behind the shared retrieval contract | `open_web_retrieval` | `open_web_retrieval` | shared infrastructure | retain as bounded extension | Keep this as optional escalation, not as a full browser-automation or anti-bot platform. |
| Shared LLM execution, cost/latency storage, and durable observability backends | `llm_client` | `llm_client` | consumed shared infrastructure | consume, do not re-own | `open_web_retrieval` can emit compatible tool-call records, but should not grow a competing runtime or storage layer. |
| Project-specific query planning, ranking policy, and downstream use of retrieved text | consuming repos (`research_v3`, `grounded-research`, `sam_gov`, others) | consuming repos | intentionally out of scope | do not absorb | Consumers decide what to search for and how to use the retrieved material. |
| Cross-repo governance, capability registry policy, and rollout enforcement | `project-meta` | `project-meta` | consumed agent platform | consume, do not re-own | This repo participates in the governed workflow but does not define it. |

## Known Consumers

Current evidence-backed consumers and adopters include:

- `research_v3`
- `grounded-research`
- `sam_gov`

Add a repo only when there is a real maintained import, integration, or
documented runtime dependency.

## Boundary Rules

1. Keep `open_web_retrieval` focused on reusable retrieval primitives and
   contracts.
2. `llm_client` owns shared execution, durable observability storage, and model
   routing; do not re-grow those boundaries here.
3. `project-meta` owns cross-repo governance, capability ownership policy, and
   rollout rules; consume that policy rather than rebuilding it locally.
4. If a new feature would make this repo a crawler, scraping framework, or
   project-specific ranking layer, stop and document the boundary decision
   before implementing it.

## Open Uncertainties

- Whether multi-provider orchestration and fallback policy should remain in
  consuming repos or become a first-class shared surface here is still open.
  `docs/plans/12_multi_provider_adapters.md` is the existing placeholder for
  that decision.
- The exact long-term boundary between local tool-call observability emission in
  this repo and richer shared observability consumption in `llm_client` is
  still evolving.
- This ownership wave intentionally keeps sanctioned worktree rollout out of
  scope; the right adoption gate for enabling worktree coordination here later
  is still unsettled.
- Optional render and anti-bot escalation backends are intentionally bounded.
  The threshold for expanding them further should stay evidence-driven rather
  than becoming a general scraping-arms-race commitment.

## Medium Adapters (worktree: medium-retrieval, 2026-06-26)

The following adapters are Medium-specific retrieval surfaces developed in the
`medium-retrieval` worktree. They belong under the
`open_web_retrieval.normalized_web_retrieval_and_provenance` family.

| Boundary | Description |
|---|---|
| `open_web_retrieval.medium_feed` | Read full article text from a Medium author/publication RSS feed |
| `open_web_retrieval.medium_get_article` | Fetch a Medium article's full text via cookie/Freedium/archive ladder |
| `open_web_retrieval.medium_search` | Search Medium articles via Brave (site:medium.com scope) |
