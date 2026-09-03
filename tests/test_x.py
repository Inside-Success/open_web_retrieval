"""X (Twitter) twitterapi.io credential and normalization contracts."""

from __future__ import annotations

import httpx
import pytest

from open_web_retrieval.adapters.base import ProviderThrottle
from open_web_retrieval.adapters.x import XSearchAdapter
from open_web_retrieval.exceptions import ProviderUnavailableError
from open_web_retrieval.models import SearchQuery


def _adapter(handler, api_key: str | None = "key") -> XSearchAdapter:
    return XSearchAdapter(
        api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        request_throttle=ProviderThrottle("x", requests_per_minute=0),
    )


def test_explicit_empty_key_never_falls_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("TWITTERAPI_IO_API_KEY", "real-environment-secret")
    requests: list[httpx.Request] = []
    adapter = _adapter(
        lambda request: requests.append(request) or httpx.Response(500, request=request),
        api_key="",
    )
    with pytest.raises(ProviderUnavailableError, match="TWITTERAPI_IO_API_KEY"):
        adapter.search(SearchQuery(query="q", providers=("x",)))
    assert requests == []


def test_missing_key_fails_before_http(monkeypatch) -> None:
    monkeypatch.delenv("TWITTERAPI_IO_API_KEY", raising=False)
    requests: list[httpx.Request] = []
    adapter = XSearchAdapter(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500, request=request))),
        request_throttle=ProviderThrottle("x", requests_per_minute=0),
    )
    with pytest.raises(ProviderUnavailableError, match="TWITTERAPI_IO_API_KEY"):
        adapter.search(SearchQuery(query="q", providers=("x",)))
    assert requests == []


def test_search_normalizes_tweets_and_caps_top_k() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-API-Key"] == "key"
        return httpx.Response(200, json={"tweets": [
            {
                "id": "1", "url": "https://x.com/opsbot/status/1",
                "text": "postmortem: agent loop root cause",
                "createdAt": "Thu Sep 03 11:34:12 +0000 2026",
                "likeCount": 42, "retweetCount": 3, "replyCount": 1, "viewCount": 900,
                "author": {"userName": "opsbot", "followers": 500, "isVerified": False, "isBlueVerified": True},
            },
            {
                "id": "2", "url": "https://x.com/other/status/2", "text": "second",
                "createdAt": "Thu Sep 03 10:00:00 +0000 2026",
                "likeCount": 1, "retweetCount": 0, "replyCount": 0, "viewCount": 10,
                "author": {"userName": "other"},
            },
        ]}, request=request)

    adapter = _adapter(handler)
    hits = adapter.search(SearchQuery(query="agent loop", providers=("x",), top_k=1))
    assert len(requests) == 1
    assert len(hits) == 1
    hit = hits[0]
    assert hit.provider == "x"
    assert hit.url == "https://x.com/opsbot/status/1"
    assert hit.title == "postmortem: agent loop root cause"
    assert hit.publisher == "@opsbot"
    assert hit.published_at is not None and hit.published_at.year == 2026
    assert hit.score_hint == 42.0
    assert hit.raw_payload["author_verified"] is True
    assert hit.raw_payload["retweet_count"] == 3


def test_domain_scoping_unsupported() -> None:
    adapter = _adapter(lambda request: httpx.Response(500, request=request))
    from open_web_retrieval.exceptions import CapabilityNotSupportedError
    with pytest.raises(CapabilityNotSupportedError):
        adapter.search(SearchQuery(query="q", providers=("x",), domains_allow=["example.com"]))
