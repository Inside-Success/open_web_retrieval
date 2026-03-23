# open_web_retrieval

`open_web_retrieval` is the shared open-web retrieval substrate. It centralizes
search providers, fetch/render behavior, and extraction into one reusable package.

## Supported v0 Capabilities

- Search adapters:
  - Brave API (`brave`)
  - SearxNG (`searxng`)
- Fetch:
  - Direct HTTP fetch via `httpx`
- Render:
 - Optional Playwright fallback (`render_mode="always"`)
- Extract:
  - Trafilatura when available
  - Fallback HTML stripping parser

## Quick Start

```python
from open_web_retrieval.client import OpenWebRetrievalClient
from open_web_retrieval.models import SearchQuery

client = OpenWebRetrievalClient(
    brave_api_key="... optional ...",
    searxng_base_url="http://localhost:8080",
)

query = SearchQuery(query="ontology alignment best practices", providers=["searxng"], top_k=3)
batch = client.retrieve(query)
print(len(batch.records))
```

## Core API

- `SearchQuery`, `SearchHit`, `FetchRequest`, `FetchedResource`,
  `ExtractedDocument`, `SourceRecord`
- `OpenWebRetrievalClient.search(...)`
- `OpenWebRetrievalClient.retrieve(...)`

## Error Contracts

All exceptions are in `open_web_retrieval.exceptions` and include stable codes:

- `OPEN_WEB_RETRIEVAL_PROVIDER_UNAVAILABLE`
- `OPEN_WEB_RETRIEVAL_RETRIEVAL_ERROR`
- `OPEN_WEB_RETRIEVAL_FETCH_ERROR`
- `OPEN_WEB_RETRIEVAL_RENDER_ERROR`
- `OPEN_WEB_RETRIEVAL_CAPABILITY_UNSUPPORTED`

## Notes

- This v0 intentionally avoids project-specific ranking, synthesis, or policy
  logic.
- Consumers should preserve this substrate contract and avoid hand-rolled generic
  internet-search/fetch/extract logic unless a capability gap is formally
  documented and approved.
