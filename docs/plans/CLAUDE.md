# Implementation Plans

Last updated: 2026-04-08

Track all implementation work here.

This file is the canonical plan-index contract for `docs/plans/`.
`docs/plans/AGENTS.md` mirrors it for Codex-facing loading.

## Gap Summary

| # | Name | Priority | Status | Blocks |
|---|------|----------|--------|--------|
| 1 | [Fetch Error Classification](01_fetch_resilience_and_crawl4ai.md) | High | ✅ Complete | - |
| 2 | [Robust Fetch (v0.3)](02_robust_fetch.md) | High | ✅ Complete | 1 |
| 3 | [Enhanced Extraction (v0.4)](03_enhanced_extraction.md) | Medium | ✅ Complete | 2 |
| 4 | [Hardening and v1.0 Prep](04_hardening_and_v1_prep.md) | Medium | ✅ Complete | 1-3 |
| 5 | [Crawl4AI Anti-Bot Escalation (v0.5)](05_crawl4ai_antibot.md) | Medium | ✅ Complete | 1-4 |
| 6 | [Autonomous 24-Hour Execution](06_autonomous_24h_execution.md) | High | ✅ Complete | - |
| 7 | [Review Fixes — Docs, Architecture, Code Smells](07_review_fixes.md) | High | ✅ Complete | - |
| 8 | [Async/Sync Deduplication](08_async_dedup.md) | High | 📋 Planned | 7 |
| 9 | [grounded-research Retrieval Follow-Ups](09_grounded_research_followups.md) | High | ✅ Complete | - |
| 10 | [Tavily Provider Parity](10_tavily_provider_parity.md) | High | ✅ Complete | research complete |
| 11 | [Exa Provider Parity](11_exa_provider_parity.md) | High | ✅ Complete | research complete |
| 12 | [Multi-Provider Search & Fetch Adapters](12_multi_provider_adapters.md) | Medium | 📋 Planned | - |
| 13 | [Governed Baseline And Capability Ownership Rollout](13_governed-baseline-and-capability-ownership-rollout.md) | High | ✅ Complete | - |
| 14 | [Authoritative coordination Wave 8 rollout](14_authoritative-coordination-wave-8-rollout.md) | High | ✅ Complete | - |
| 15 | [Retrieval Control Surface and Behavior Verification](15_retrieval_control_surface_and_behavior_verification.md) | High | ✅ Complete | - |
| 16 | [Exa Retrieval Instruction Surface](16_exa_retrieval_instruction_surface.md) | High | ✅ Complete | 15 |

## Status Key

| Status | Meaning |
|--------|---------|
| ❌ Needs Plan | Gap identified, no plan yet |
| 📋 Planned | Ready to implement |
| 🚧 In Progress | Being worked on |
| ⏸️ Blocked | Waiting on dependency |
| ✅ Complete | Implemented and verified |

## Creating a New Plan

1. Copy `TEMPLATE.md` to `NN_name.md`
2. Fill in gap, steps, required tests
3. Add to this index
4. Commit with `[Plan #N]` prefix

## Trivial Changes

Not everything needs a plan. Use `[Trivial]` for:
- Less than 20 lines changed
- No changes to `src/` (production code)
- No new files created

```bash
git commit -m "[Trivial] Fix typo in README"
```

## Completing Plans

```bash
python scripts/meta/complete_plan.py --plan N
```

This verifies tests pass and records completion evidence.
