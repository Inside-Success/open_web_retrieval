# Open Web Retrieval Artifact Register

Wiki home: http://localhost:8088/index.php/Project_Wiki

## Primary Reviewer Artifacts

| Artifact | Role | Portfolio meaning |
|---|---|---|
| [PROJECT.md](../PROJECT.md) | Dossier entrypoint | Frames this as supporting retrieval infrastructure. |
| [README.md](../README.md) | Project overview | Installation, API examples, and feature summary. |
| [docs/RETRIEVAL_TRACE_EXAMPLE.md](RETRIEVAL_TRACE_EXAMPLE.md) | Portfolio guide | Defines the applied trace shape reviewers should inspect. |
| [docs/REQUIREMENTS.md](REQUIREMENTS.md) | Requirements | Scope, consumers, success criteria, and failure criteria. |
| [docs/ROADMAP.md](ROADMAP.md) | Roadmap | Versioned implementation history and future direction. |
| [docs/SOTA_RESEARCH.md](SOTA_RESEARCH.md) | Research synthesis | Borrow-vs-build context for fetch/extraction tooling. |
| [docs/ops/CAPABILITY_DECOMPOSITION.md](ops/CAPABILITY_DECOMPOSITION.md) | Ownership ledger | Defines shared capability boundaries. |
| [docs/METHODOLOGY.md](METHODOLOGY.md) | Methodology spine | Explains retrieval method and failure modes. |
| [docs/VALIDATION.md](VALIDATION.md) | Validation register | Defines implementation and portfolio evidence gaps. |
| [docs/CONCERNS.md](CONCERNS.md) | Concern register | Tracks open risks. |

## Code And Execution Surfaces

| Surface | Role |
|---|---|
| `src/open_web_retrieval/models.py` | Pydantic contracts for search/fetch/extract/provenance. |
| `src/open_web_retrieval/client.py` | Sync retrieval orchestration. |
| `src/open_web_retrieval/async_client.py` | Async retrieval orchestration. |
| `src/open_web_retrieval/fetch_extract.py` | Fetch, render, extraction, and SPA detection. |
| `src/open_web_retrieval/adapters/` | Brave, SearxNG, Tavily, Exa, and tool adapters. |
| `src/open_web_retrieval/cache.py` | Disk cache, TTL, locking, and LRU behavior. |
| `src/open_web_retrieval/observability.py` | Tool-call logger protocol. |
| `tests/` | Unit and adapter behavior tests. |

## Evidence Artifacts

| Artifact | Evidence | Notes |
|---|---|---|
| [docs/REQUIREMENTS.md](REQUIREMENTS.md) | Scope and shipped capabilities | Best contract document. |
| [docs/ROADMAP.md](ROADMAP.md) | Shipped version history | Shows feature progression through v0.11.0 and the agent-retrieval MVP gates. |
| [docs/SOTA_RESEARCH.md](SOTA_RESEARCH.md) | Tool landscape | Documents why httpx/trafilatura plus bounded escalation was chosen. |
| [docs/notebooks/04_retrieval_control_surface_and_behavior_verification.ipynb](notebooks/04_retrieval_control_surface_and_behavior_verification.ipynb) | Control-surface verification | Notebook artifact for retrieval controls. |
| [docs/notebooks/05_exa_retrieval_instruction_surface.ipynb](notebooks/05_exa_retrieval_instruction_surface.ipynb) | Exa instruction surface | Notebook artifact for provider instruction behavior. |

## Missing Portfolio Artifacts

- One applied trace from a downstream project claim or citation.
- A compact source-path table showing query, provider, URL, fetch, extraction,
  and downstream use.
- A visible example of partial failure handling.
- A consumer integration note from `grounded-research` or `research_v3`.
