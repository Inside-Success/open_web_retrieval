# Plan #03: Enhanced Extraction (v0.4)

**Status:** Complete
**Type:** implementation
**Priority:** Medium
**Blocked By:** Plan #02 (complete)
**Blocks:** LLM-ready output for research_v3 and future agents

---

## Gap

**Current (v0.3):** Extraction produces plain text only. Consumers wanting markdown
must post-process. Metadata fields (title, author, date) exist on `ExtractedDocument`
but are always None — trafilatura extracts them, we just don't read them. Search
results from multiple providers can duplicate URLs.

**Target (v0.4):** Extraction produces markdown by default. Metadata fields are
populated. Search dedup removes duplicate URLs across providers.

**Why:** LLM consumers (research_v3 loop, future agents) work better with markdown
(preserves structure — headers, lists, links) than raw text. Metadata enables
provenance tracking (who published this, when).

---

## References Reviewed

- `src/open_web_retrieval/fetch_extract.py:92-108` — current `_extract_with_trafilatura()`
- `src/open_web_retrieval/models.py:103-116` — `ExtractedDocument` (title, publisher, date always None)
- `trafilatura.extract()` — supports `output_format="markdown"`, `include_links=True`
- `trafilatura.bare_extraction()` — returns Document with title, author, date, sitename
- `src/open_web_retrieval/client.py:79-127` — `search()` method, no dedup

Tested locally: trafilatura already outputs markdown with metadata frontmatter.
`bare_extraction()` returns structured Document with `.title`, `.author`, `.date`,
`.sitename` attributes.

---

## Pre-made Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Markdown via trafilatura, not Jina/Crawl4AI | Yes | Already a dependency. `output_format="markdown"` just works. No new deps. |
| Default output format | `markdown` (change from `txt`) | Consumers want structure. Breaking change but no consumer reads `extraction_method` to decide format. |
| Metadata source | `bare_extraction()` for metadata, `extract()` for content | bare_extraction returns Document object with typed fields |
| Search dedup | By URL, keep first occurrence (highest rank) | Simple. Provider order determines priority. |
| `include_links` in markdown | Yes, default on | Links are valuable for provenance. Configurable. |

---

## Files Affected

- `src/open_web_retrieval/fetch_extract.py` (modify — markdown output, metadata extraction)
- `src/open_web_retrieval/models.py` (modify — add `markdown` field to ExtractedDocument)
- `src/open_web_retrieval/client.py` (modify — search dedup)
- `tests/test_fetch_extract.py` (modify — markdown and metadata tests)
- `tests/test_client.py` (modify — dedup test)

---

## Plan

### Step 1: Add `markdown` field to ExtractedDocument

```python
# models.py
class ExtractedDocument(BaseModel):
    ...
    text: str                    # plain text (existing)
    markdown: str = ""           # markdown with structure preserved (new)
```

Backward compatible — `text` still exists, `markdown` is additive.

### Step 2: Extract metadata via bare_extraction

Replace `_extract_with_trafilatura()` with a richer version that returns both
content and metadata:

```python
def _extract_with_trafilatura(html_text: str, url: str | None = None) -> tuple[str, str, dict] | None:
    """Extract text, markdown, and metadata from HTML via trafilatura."""
    from trafilatura import bare_extraction, extract

    # Get structured metadata
    doc = bare_extraction(html_text, url=url, with_metadata=True)

    # Get markdown content
    md = extract(html_text, output_format="markdown", include_links=True,
                 include_tables=True, url=url)

    # Get plain text
    txt = extract(html_text, output_format="txt", url=url)

    metadata = {}
    if doc:
        metadata = {
            "title": doc.title,
            "author": doc.author,
            "date": doc.date,
            "sitename": doc.sitename,
        }

    return txt or "", md or "", metadata
```

### Step 3: Wire metadata into ExtractedDocument

In `SourceFetcher.extract()`, populate the metadata fields that are currently
always None:

```python
def extract(self, resource, *, method="trafilatura"):
    text, markdown, metadata, method_used, warnings = _extract_text(resource, method=method)
    return ExtractedDocument(
        ...
        title=metadata.get("title"),
        publisher_guess=metadata.get("sitename") or metadata.get("author"),
        published_at_guess=_parse_date(metadata.get("date")),
        text=text,
        markdown=markdown,
        ...
    )
```

### Step 4: Search result deduplication

In `OpenWebRetrievalClient.search()`, dedup by URL before returning:

```python
def search(self, query):
    ...
    # Dedup by URL — keep first occurrence (highest-ranked provider)
    seen_urls: set[str] = set()
    deduped: list[SearchHit] = []
    for hit in combined_hits:
        if hit.url not in seen_urls:
            seen_urls.add(hit.url)
            deduped.append(hit)
    return deduped[:query.top_k]
```

### Step 5: Tests

| Test | What It Verifies |
|------|------------------|
| `test_extract_produces_markdown` | ExtractedDocument.markdown is non-empty for HTML input |
| `test_extract_metadata_populated` | title, publisher_guess, published_at_guess filled from HTML |
| `test_extract_plain_text_still_works` | ExtractedDocument.text still populated |
| `test_extract_markdown_includes_links` | Links preserved in markdown output |
| `test_search_dedup_by_url` | Duplicate URLs from 2 providers → kept once |
| `test_search_dedup_preserves_order` | First occurrence (highest rank) wins |

---

## Acceptance Criteria

- [x] `ExtractedDocument` has `markdown: str` field
- [x] Markdown output includes headers, links, tables from HTML
- [x] `title`, `publisher_guess`, `published_at_guess` populated from trafilatura metadata
- [x] Search results deduplicated by URL across providers
- [x] All existing tests pass (87 from v0.3)
- [x] 11 new tests (exceeded plan: 4 extraction + 2 frontmatter + 3 date parsing + 2 dedup)
- [ ] **Gate: research_v3 loop receives markdown from ExtractedDocument when using open_web_retrieval** — Deferred; library-side verified via e2e_test.py

---

## Budget

~1.5 hours:
- Steps 1-3 (markdown + metadata): ~45 minutes
- Step 4 (search dedup): ~15 minutes
- Step 5 (tests): ~30 minutes

---

## Notes

- trafilatura's markdown output includes YAML frontmatter (title, url, date) when
  `with_metadata=True` is passed to `extract()`. We strip this and put metadata in
  the Pydantic fields instead — consumers shouldn't parse frontmatter.
- The `text` field remains for backward compatibility. Consumers that want markdown
  read `markdown`; consumers that want plain text read `text`.
- `bare_extraction()` calls trafilatura's parser twice (once for metadata, once for
  content). If this becomes a perf issue, we can cache the parse tree. Not worth
  optimizing now.
