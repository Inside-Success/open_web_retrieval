"""The shared provider throttle, and the Reddit OAuth search adapter.

WHY THE THROTTLE EXISTS. ``rate_limit_per_second`` on the client paces PAGE
FETCHES per domain inside async_fetch. Search adapters each hold their own
httpx.Client and never touch it, so every keyless provider was unpaced: the
hackernews adapter had no limit at all, and the arxiv adapter had a DOCSTRING
saying "pacing belongs to the caller" - a note, not a guard. One throttle in the
base class means a new adapter cannot silently skip it.

WHY THE REDDIT ADAPTER EXISTS. On a live grounded-research run (2026-07-27) six
Reddit URLs needed the fetch fallback because Reddit blocks generic page fetches.
Web-search-then-fetch keeps arriving at Reddit's front door and being turned
away; querying Reddit's own index sidesteps that.

Reddit numbers here are MEASURED, not guessed: the live API returned
x-ratelimit-remaining 998 of 1000 with a 546s reset (2026-07-28).
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from open_web_retrieval.adapters import base
from open_web_retrieval.exceptions import (
    CapabilityNotSupportedError,
    ProviderUnavailableError,
    RetrievalError,
)
from open_web_retrieval.models import SearchQuery

CREDS = dict(
    client_id="id", client_secret="secret",
    username="bot", password="pw",
)


@pytest.fixture(autouse=True)
def _clear_throttles():
    """Throttles are process-wide singletons; env overrides need a fresh one."""
    base.reset_throttles()
    yield
    base.reset_throttles()


# ── the throttle ────────────────────────────────────────────────────────────

class TestThrottle:
    """Per-provider pacing shared by every adapter."""

    def test_measured_reddit_limit_sits_inside_the_real_ceiling(self):
        """Reddit allows ~1000 per 10 minutes (measured). The default must leave
        real headroom: 100/min IS the 10-minute average, so sustaining it trips
        the window on any burst. This test caught exactly that."""
        rpm, concurrency = base.provider_limits("reddit")
        assert rpm <= 100
        assert rpm * 10 < 1000, "10-minute burst must stay under Reddit's window"
        assert concurrency == 2

    def test_arxiv_is_serialized_because_arxiv_asks_for_it(self):
        rpm, concurrency = base.provider_limits("arxiv")
        assert concurrency == 1
        assert 60.0 / rpm >= 3.0, "arXiv asks for ~1 request per 3 seconds"

    def test_api_key_providers_are_not_paced_by_default(self):
        """brave/tavily/exa ceilings are a billing matter with the vendor.
        Adding an unrequested delay to a PAID call would be a surprise."""
        for provider in ("brave", "tavily", "exa"):
            rpm, _ = base.provider_limits(provider)
            assert rpm == 0, f"{provider} must not be silently throttled"

    def test_env_overrides_the_table(self, monkeypatch):
        monkeypatch.setenv("OWR_RPM_REDDIT", "40")
        monkeypatch.setenv("OWR_CONCURRENCY_REDDIT", "5")
        assert base.provider_limits("reddit") == (40, 5)

    def test_garbage_env_falls_back_instead_of_crashing(self, monkeypatch):
        """A typo in an env var must not take the whole run down."""
        monkeypatch.setenv("OWR_RPM_REDDIT", "not-a-number")
        rpm, _ = base.provider_limits("reddit")
        assert rpm == base._PROVIDER_LIMITS["reddit"][0]

    def test_rpm_zero_disables_spacing(self, monkeypatch):
        monkeypatch.setenv("OWR_RPM_REDDIT", "0")
        assert base._Throttle("reddit").min_interval == 0.0

    def test_it_actually_spaces_calls(self, monkeypatch):
        """The point of the exercise: successive calls are separated in time."""
        monkeypatch.setenv("OWR_RPM_HACKERNEWS", "600")  # 0.1s apart
        throttle = base._Throttle("hackernews")
        start = time.monotonic()
        for _ in range(4):
            with throttle.hold():
                pass
        # first is free, next three each wait an interval
        assert time.monotonic() - start >= 0.28

    def test_it_caps_concurrency(self, monkeypatch):
        monkeypatch.setenv("OWR_RPM_ARXIV", "0")  # isolate concurrency from spacing
        throttle = base._Throttle("arxiv")  # concurrency 1
        peak = {"now": 0, "max": 0}
        guard = threading.Lock()

        def worker():
            with throttle.hold():
                with guard:
                    peak["now"] += 1
                    peak["max"] = max(peak["max"], peak["now"])
                time.sleep(0.05)
                with guard:
                    peak["now"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert peak["max"] == 1, f"arxiv must be serialized, saw {peak['max']} in flight"

    def test_throttle_is_shared_per_provider(self):
        """Two adapter instances must contend for the SAME slot, or the cap is a
        suggestion rather than a limit."""
        assert base.throttle_for("reddit") is base.throttle_for("reddit")
        assert base.throttle_for("reddit") is not base.throttle_for("arxiv")

    def test_every_keyless_adapter_routes_through_paced(self):
        """A new adapter that forgets `with self.paced()` silently bypasses the
        limiter, so pin it at the source."""
        import inspect

        from open_web_retrieval.adapters.arxiv import ArxivSearchAdapter
        from open_web_retrieval.adapters.hackernews import HackerNewsSearchAdapter
        from open_web_retrieval.adapters.reddit import RedditSearchAdapter

        for cls in (ArxivSearchAdapter, HackerNewsSearchAdapter, RedditSearchAdapter):
            src = inspect.getsource(cls)
            assert "with self.paced()" in src, f"{cls.__name__} is not paced"


# ── the Reddit adapter ──────────────────────────────────────────────────────

def _post(pid="abc", *, sub="ClaudeAI", title="An overnight agent loop locked my account",
          selftext="", score=42, created=1785000000.0, url=None):
    permalink = f"/r/{sub}/comments/{pid}/slug/"
    return {"data": {
        "permalink": permalink, "subreddit": sub, "title": title,
        "selftext": selftext, "score": score, "num_comments": 17,
        "author": "someone", "created_utc": created, "upvote_ratio": 0.95,
        "url": url or f"https://reddit.com{permalink}",
    }}


def _adapter(handler):
    from open_web_retrieval.adapters.reddit import RedditSearchAdapter

    return RedditSearchAdapter(
        **CREDS, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _ok_auth_then(search_response):
    """Handler that answers the token call, then the search call."""
    def handler(req):
        if "access_token" in str(req.url):
            return httpx.Response(200, json={
                "access_token": "tok", "expires_in": 86400, "scope": "*"}, request=req)
        return search_response(req)
    return handler


class TestRedditAuth:
    """Credential failures must name WHICH credential - verified against the
    live API 2026-07-28, where app-secret and account-login failures return
    different shapes and are trivially confused."""

    def test_missing_credentials_named_explicitly(self):
        from open_web_retrieval.adapters.reddit import RedditSearchAdapter

        adapter = RedditSearchAdapter(client_id="", client_secret="s",
                                      username="", password="p")
        with pytest.raises(ProviderUnavailableError) as exc:
            adapter.search(SearchQuery(query="q", providers=("reddit",)))
        assert "REDDIT_CLIENT_ID" in str(exc.value)
        assert "REDDIT_USERNAME" in str(exc.value)

    def test_401_blames_the_app_credentials(self):
        """Reddit returns 401 when CLIENT_ID/SECRET are wrong."""
        adapter = _adapter(lambda req: httpx.Response(401, request=req))
        with pytest.raises(ProviderUnavailableError, match="app credentials"):
            adapter.search(SearchQuery(query="q", providers=("reddit",)))

    def test_200_with_error_blames_the_account_login(self):
        """Reddit returns 200 + {"error": ...} when USERNAME/PASSWORD are wrong,
        or when the account has 2FA the script grant cannot satisfy."""
        adapter = _adapter(
            lambda req: httpx.Response(200, json={"error": "invalid_grant"}, request=req))
        with pytest.raises(ProviderUnavailableError, match="account login"):
            adapter.search(SearchQuery(query="q", providers=("reddit",)))

    def test_token_is_reused_not_reminted_per_search(self):
        """The script grant lasts ~24h. Minting per search would waste the
        rate-limit budget the searches need."""
        calls = []

        def handler(req):
            calls.append(str(req.url))
            if "access_token" in str(req.url):
                return httpx.Response(200, json={
                    "access_token": "tok", "expires_in": 86400}, request=req)
            return httpx.Response(200, json={"data": {"children": []}}, request=req)

        adapter = _adapter(handler)
        for _ in range(3):
            adapter.search(SearchQuery(query="q", providers=("reddit",)))
        assert sum("access_token" in c for c in calls) == 1

    def test_a_401_on_search_drops_the_cached_token(self):
        """A revoked app or changed password invalidates a cached token; keeping
        it would loop forever on a dead credential."""
        adapter = _adapter(_ok_auth_then(lambda req: httpx.Response(401, request=req)))
        with pytest.raises(RetrievalError, match="invalidated"):
            adapter.search(SearchQuery(query="q", providers=("reddit",)))
        assert adapter._token is None


class TestRedditSearch:
    """Normalization."""

    def test_url_is_the_discussion_permalink(self):
        adapter = _adapter(_ok_auth_then(
            lambda req: httpx.Response(200, json={"data": {"children": [_post()]}}, request=req)))
        hit = adapter.search(SearchQuery(query="q", providers=("reddit",), top_k=1))[0]
        assert hit.url == "https://reddit.com/r/ClaudeAI/comments/abc/slug/"
        assert hit.publisher == "r/ClaudeAI"

    def test_upvotes_never_masquerade_as_a_relevance_score(self):
        """Reddit scores are unbounded AND vote-fuzzed, so they cannot share a
        scale with Tavily's 0-1 score_hint."""
        adapter = _adapter(_ok_auth_then(
            lambda req: httpx.Response(
                200, json={"data": {"children": [_post(score=9100)]}}, request=req)))
        hit = adapter.search(SearchQuery(query="q", providers=("reddit",), top_k=1))[0]
        assert hit.score_hint is None
        assert hit.raw_payload["score"] == 9100

    def test_long_selftext_rides_raw_content(self):
        body = "We ran unattended agent loops for six months and here is what broke. " * 3
        adapter = _adapter(_ok_auth_then(
            lambda req: httpx.Response(
                200, json={"data": {"children": [_post(selftext=body)]}}, request=req)))
        hit = adapter.search(SearchQuery(query="q", providers=("reddit",), top_k=1))[0]
        assert hit.raw_payload["raw_content"].startswith("We ran unattended")
        assert len(hit.snippet) <= 400

    def test_post_without_a_permalink_is_skipped(self):
        adapter = _adapter(_ok_auth_then(
            lambda req: httpx.Response(200, json={"data": {"children": [
                {"data": {"title": "orphan", "subreddit": "x"}}, _post("keep")]}}, request=req)))
        hits = adapter.search(SearchQuery(query="q", providers=("reddit",), top_k=5))
        assert len(hits) == 1
        assert "keep" in hits[0].url

    def test_recency_prunes_client_side(self):
        """Reddit's `t` param is coarse (day/week/month/year), so the exact day
        cutoff has to be applied here or a 3-day request returns 30-day posts."""
        now = time.time()
        adapter = _adapter(_ok_auth_then(
            lambda req: httpx.Response(200, json={"data": {"children": [
                _post("fresh", created=now - 86400),
                _post("stale", created=now - 86400 * 90),
            ]}}, request=req)))
        hits = adapter.search(
            SearchQuery(query="q", providers=("reddit",), top_k=5, recency_days=7))
        assert len(hits) == 1
        assert "fresh" in hits[0].url

    def test_published_at_from_created_utc(self):
        adapter = _adapter(_ok_auth_then(
            lambda req: httpx.Response(
                200, json={"data": {"children": [_post(created=1785000000.0)]}}, request=req)))
        hit = adapter.search(SearchQuery(query="q", providers=("reddit",), top_k=1))[0]
        assert hit.published_at is not None
        assert hit.published_at.tzinfo is not None

    def test_domains_allow_now_scopes_instead_of_raising(self):
        """CHANGED 2026-07-29: domains_allow became subreddit scoping.

        This test previously asserted that domains_allow raised
        CapabilityNotSupportedError with the message "use subreddit scoping".
        That message described a capability that did not exist; it does now, so
        the field scopes rather than rejecting. domains_DENY still raises — see
        TestSubredditScoping.
        """
        seen = {}

        def capture(req):
            seen["url"] = str(req.url)
            return httpx.Response(200, json={}, request=req)

        adapter = _adapter(_ok_auth_then(capture))
        adapter.search(SearchQuery(query="q", providers=("reddit",),
                                   domains_allow=("devops", "r/claudeai")))
        assert "subreddit%3Adevops" in seen["url"] or "subreddit:devops" in seen["url"]
        assert "subreddit%3Aclaudeai" in seen["url"] or "subreddit:claudeai" in seen["url"]

    def test_rate_limit_headers_surface_in_the_error_context(self):
        """When Reddit does throttle us, the remaining budget must reach the
        operator - otherwise the next decision is guesswork."""
        adapter = _adapter(_ok_auth_then(lambda req: httpx.Response(
            429, headers={"x-ratelimit-remaining": "0"}, request=req)))
        with pytest.raises(RetrievalError) as exc:
            adapter.search(SearchQuery(query="q", providers=("reddit",)))
        assert exc.value.context.get("ratelimit_remaining") == "0"


class TestWiring:
    def test_reddit_is_opt_in(self):
        from open_web_retrieval.client import OpenWebRetrievalClient

        assert "reddit" not in OpenWebRetrievalClient(tavily_api_key="k").adapters.adapters

    def test_enable_reddit_registers_it(self):
        from open_web_retrieval.client import OpenWebRetrievalClient

        client = OpenWebRetrievalClient(enable_reddit=True)
        assert "reddit" in client.adapters.adapters

    def test_provider_name_accepts_reddit(self):
        SearchQuery(query="q", providers=("reddit",))


class TestSubredditScoping:
    """`domains_allow` carries SUBREDDIT names for Reddit.

    Reddit has ONE host, so a domain filter is meaningless here; the adapter used
    to raise "use subreddit scoping" and now implements it.

    MEASURED against the live API 2026-07-29 (12 hits per shape) — the reason
    callers must send keywords, not a sentence:

        long sentence                        ->  0 hits
        short keywords                       -> 12 hits,  5 on-topic
        short keywords + subreddit: filter   -> 12 hits, 12 on-topic
        long sentence + subreddit: filter    ->  0 hits

    End-to-end through the real adapter: 10/10 on-topic when scoped.
    """

    @staticmethod
    def _q(**kw):
        from open_web_retrieval.models import SearchQuery
        kw.setdefault("query", "coding agents worktrees")
        kw.setdefault("providers", ("reddit",))
        return SearchQuery(**kw)

    def _scope(self, **kw) -> str:
        from open_web_retrieval.adapters.reddit import RedditSearchAdapter
        return RedditSearchAdapter._scoped_query(self._q(**kw))

    def test_no_allowlist_leaves_the_query_untouched(self) -> None:
        assert self._scope() == "coding agents worktrees"

    def test_allowlist_becomes_a_subreddit_or_filter(self) -> None:
        assert self._scope(domains_allow=("devops", "claudeai")) == (
            "(coding agents worktrees) (subreddit:devops OR subreddit:claudeai)"
        )

    def test_names_accepted_bare_or_prefixed(self) -> None:
        """A caller holding "r/devops" must not silently search for "r/devops"."""
        for name in ("devops", "r/devops", "/r/devops", "R/DevOps", " devops "):
            assert self._scope(domains_allow=(name,)) == (
                "(coding agents worktrees) (subreddit:devops)"
            ), name

    def test_duplicates_collapse_and_order_is_stable(self) -> None:
        # dict.fromkeys keeps first-seen order — a stable q means the engine's
        # search-dedup cache key stays stable across runs.
        assert self._scope(domains_allow=("b", "a", "B", "r/a")) == (
            "(coding agents worktrees) (subreddit:b OR subreddit:a)"
        )

    def test_empty_entries_are_dropped_not_emitted(self) -> None:
        # A blank would become "subreddit:" and silently return nothing.
        assert self._scope(domains_allow=("", "  ", "devops")) == (
            "(coding agents worktrees) (subreddit:devops)"
        )
        assert self._scope(domains_allow=("", "  ")) == "coding agents worktrees"

    def test_domains_deny_still_raises(self) -> None:
        """Exclusion has no Reddit equivalent — fail loud rather than ignore it."""
        import pytest

        from open_web_retrieval.adapters.reddit import RedditSearchAdapter
        from open_web_retrieval.exceptions import CapabilityNotSupportedError

        with pytest.raises(CapabilityNotSupportedError):
            RedditSearchAdapter().search(self._q(domains_deny=("spam.com",)))
