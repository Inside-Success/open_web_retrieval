"""Source-targeted keyless adapters: Hacker News and arXiv.

WHY THESE PROVIDERS EXIST. A general web index is asked to surface practitioner
evidence and SEO decides whether it does. Measured on a live grounded-research
run (2026-07-27): 44 of 50 collected sources had provenance the classifier could
not vouch for, and per-citation faithfulness landed at 0.767 against a 0.80
gate. Querying a venue's OWN index inverts that — HN's index contains HN,
arXiv's contains preprints — so the evidence type is a property of the provider
rather than a hope about ranking.

Both are keyless, so these tests are the only gate on their correctness.
"""

from __future__ import annotations

import httpx
import pytest

from open_web_retrieval.exceptions import CapabilityNotSupportedError, RetrievalError
from open_web_retrieval.models import SearchQuery


# ── Hacker News ─────────────────────────────────────────────────────────────

class TestHackerNewsAdapter:
    """The HN Algolia adapter."""

    def _hit(self, item_id, *, title="Ask HN: agent loops in prod", url=None,
             text="", points=42, created="2026-07-01T12:00:00.000Z"):
        return {
            "objectID": str(item_id),
            "title": title,
            "url": url,
            "story_text": text,
            "points": points,
            "num_comments": 17,
            "author": "someone",
            "created_at": created,
        }

    def _adapter(self, hits, *, capture=None):
        from open_web_retrieval.adapters.hackernews import HackerNewsSearchAdapter

        def handler(req):
            if capture is not None:
                capture.append(req)
            return httpx.Response(200, json={"hits": hits}, request=req)

        return HackerNewsSearchAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_url_is_the_discussion_thread_not_the_submitted_link(self):
        """The thread is the practitioner evidence and the citable unit; the
        submitted article rides the payload for a consumer that wants it."""
        adapter = self._adapter([self._hit(4213, url="https://vendor.example/post")])
        hit = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=1))[0]

        assert hit.url == "https://news.ycombinator.com/item?id=4213"
        assert hit.raw_payload["external_url"] == "https://vendor.example/post"
        assert hit.publisher == "Hacker News"

    def test_points_never_masquerade_as_a_relevance_score(self):
        """points is unbounded (front page clears 2000) and so is not comparable
        to Tavily's 0-1 score_hint. Same landmine OpenAlex documents."""
        adapter = self._adapter([self._hit(1, points=3100)])
        hit = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=1))[0]

        assert hit.score_hint is None
        assert hit.raw_payload["points"] == 3100

    def test_long_submission_text_rides_raw_content(self):
        """A blocked fetch must still leave verifiable text behind."""
        body = "We ran unattended agent loops for six months and here is what broke. " * 3
        adapter = self._adapter([self._hit(1, text=body)])
        hit = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=1))[0]

        assert hit.raw_payload["raw_content"].startswith("We ran unattended agent loops")
        assert len(hit.snippet) <= 400

    def test_short_text_does_not_ride_raw_content(self):
        adapter = self._adapter([self._hit(1, text="too short")])
        hit = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=1))[0]
        assert "raw_content" not in hit.raw_payload

    def test_entry_without_an_id_is_skipped(self):
        """No objectID means no citable thread URL — dropping beats minting a
        broken citation."""
        adapter = self._adapter([{"title": "orphan", "points": 5}, self._hit(9)])
        hits = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=5))
        assert [h.url for h in hits] == ["https://news.ycombinator.com/item?id=9"]

    def test_searches_stories_only(self):
        """A bare comment has no title and no standalone URL; the thread is the
        citable unit and its comments arrive when a consumer fetches it."""
        seen = []
        self._adapter([], capture=seen).search(
            SearchQuery(query="q", providers=("hackernews",), top_k=3)
        )
        assert "tags=story" in str(seen[0].url)

    def test_recency_becomes_a_numeric_filter(self):
        seen = []
        self._adapter([], capture=seen).search(
            SearchQuery(query="q", providers=("hackernews",), top_k=3, recency_days=30)
        )
        assert "numericFilters=created_at_i" in str(seen[0].url)

    def test_published_at_parsed_to_utc(self):
        adapter = self._adapter([self._hit(1, created="2026-07-01T12:00:00.000Z")])
        hit = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=1))[0]
        assert hit.published_at.year == 2026 and hit.published_at.month == 7

    def test_top_k_is_respected(self):
        adapter = self._adapter([self._hit(i) for i in range(10)])
        hits = adapter.search(SearchQuery(query="q", providers=("hackernews",), top_k=3))
        assert len(hits) == 3
        assert [h.rank for h in hits] == [1, 2, 3]

    def test_domain_filters_raise_capability_error(self):
        adapter = self._adapter([])
        with pytest.raises(CapabilityNotSupportedError):
            adapter.search(
                SearchQuery(query="q", providers=("hackernews",), domains_allow=("x.org",))
            )

    def test_http_error_raises_retrieval_error(self):
        from open_web_retrieval.adapters.hackernews import HackerNewsSearchAdapter

        transport = httpx.MockTransport(lambda req: httpx.Response(503, request=req))
        adapter = HackerNewsSearchAdapter(client=httpx.Client(transport=transport))
        with pytest.raises(RetrievalError):
            adapter.search(SearchQuery(query="q", providers=("hackernews",)))


# ── arXiv ───────────────────────────────────────────────────────────────────

_ATOM_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
{entries}
</feed>"""

_ENTRY = """  <entry>
    <id>http://arxiv.org/abs/{num}v1</id>
    <published>{published}</published>
    <updated>{published}</updated>
    <title>Correlated Errors in
      Large Language Models</title>
    <summary>{summary}</summary>
    <author><name>A. Researcher</name></author>
    <author><name>B. Coauthor</name></author>
    <link href="http://arxiv.org/abs/{num}v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/{num}v1" rel="related"/>
    <category term="cs.AI"/>
  </entry>"""


class TestArxivAdapter:
    """The arXiv Atom adapter."""

    def _feed(self, *entries):
        return _ATOM_TEMPLATE.format(entries="\n".join(entries))

    def _entry(self, num, published="2026-07-01T00:00:00Z", summary="A" * 200):
        return _ENTRY.format(num=num, published=published, summary=summary)

    def _adapter(self, body, *, capture=None, status=200):
        from open_web_retrieval.adapters.arxiv import ArxivSearchAdapter

        def handler(req):
            if capture is not None:
                capture.append(req)
            return httpx.Response(status, text=body, request=req)

        return ArxivSearchAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_parses_atom_and_collapses_wrapped_titles(self):
        """arXiv wraps titles at 80 columns; a citation must not carry newlines."""
        adapter = self._adapter(self._feed(self._entry("2605.29800")))
        hit = adapter.search(SearchQuery(query="q", providers=("arxiv",), top_k=1))[0]

        assert hit.title == "Correlated Errors in Large Language Models"
        assert "\n" not in hit.title
        assert hit.url == "http://arxiv.org/abs/2605.29800v1"
        assert hit.publisher == "arXiv"

    def test_abstract_rides_raw_content_and_pdf_rides_payload(self):
        adapter = self._adapter(self._feed(self._entry("1")))
        hit = adapter.search(SearchQuery(query="q", providers=("arxiv",), top_k=1))[0]

        assert hit.raw_payload["raw_content"].startswith("AAA")
        assert hit.raw_payload["pdf_url"] == "http://arxiv.org/pdf/1v1"
        assert hit.raw_payload["authors"] == ["A. Researcher", "B. Coauthor"]
        assert hit.raw_payload["categories"] == ["cs.AI"]

    def test_no_synthesized_relevance_score(self):
        """arXiv returns no score. None is the honest value — do not derive one
        from rank and let a consumer compare it against Tavily's."""
        adapter = self._adapter(self._feed(self._entry("1")))
        hit = adapter.search(SearchQuery(query="q", providers=("arxiv",), top_k=1))[0]
        assert hit.score_hint is None

    def test_recency_sorts_by_date_and_prunes_old_entries(self):
        seen = []
        body = self._feed(
            self._entry("new", published="2026-07-20T00:00:00Z"),
            self._entry("old", published="2019-01-01T00:00:00Z"),
        )
        adapter = self._adapter(body, capture=seen)
        hits = adapter.search(
            SearchQuery(query="q", providers=("arxiv",), top_k=5, recency_days=60)
        )

        assert [h.url for h in hits] == ["http://arxiv.org/abs/newv1"]
        assert "sortBy=submittedDate" in str(seen[0].url)

    def test_relevance_sort_when_no_recency_requested(self):
        seen = []
        self._adapter(self._feed(), capture=seen).search(
            SearchQuery(query="q", providers=("arxiv",), top_k=5)
        )
        assert "sortBy=relevance" in str(seen[0].url)

    def test_non_xml_body_raises_instead_of_returning_empty(self):
        """arXiv answers 200 with an HTML error page on some malformed queries.
        Returning [] would read to a consumer as 'no such research exists'."""
        adapter = self._adapter("<html><body>Bad Request</body></html>")
        with pytest.raises(RetrievalError):
            adapter.search(SearchQuery(query="q", providers=("arxiv",)))

    def test_domain_filters_raise_capability_error(self):
        adapter = self._adapter(self._feed())
        with pytest.raises(CapabilityNotSupportedError):
            adapter.search(SearchQuery(query="q", providers=("arxiv",), domains_allow=("x.org",)))


# ── wiring ──────────────────────────────────────────────────────────────────

class TestClientWiring:
    """Both providers must be opt-in so existing consumers are unchanged."""

    def test_keyless_providers_satisfy_the_no_providers_check(self):
        from open_web_retrieval.client import OpenWebRetrievalClient

        client = OpenWebRetrievalClient(enable_hackernews=True, enable_arxiv=True)
        assert set(client.adapters.adapters) == {"hackernews", "arxiv"}

    def test_not_enabled_by_default(self):
        from open_web_retrieval.client import OpenWebRetrievalClient

        client = OpenWebRetrievalClient(tavily_api_key="k")
        assert "hackernews" not in client.adapters.adapters
        assert "arxiv" not in client.adapters.adapters

    def test_provider_names_are_accepted_by_the_model(self):
        """ProviderName is a closed Literal — the adapters are useless if the
        new names were not added to it."""
        SearchQuery(query="q", providers=("hackernews", "arxiv"))
