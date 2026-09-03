"""GitHub repository search credential and normalization contracts."""

from __future__ import annotations

import httpx
import pytest

from open_web_retrieval.adapters.base import ProviderThrottle
from open_web_retrieval.adapters.github import GitHubSearchAdapter
from open_web_retrieval.exceptions import ProviderUnavailableError, RetrievalError
from open_web_retrieval.models import SearchQuery


def _adapter(handler, api_key: str | None = "token") -> GitHubSearchAdapter:
    return GitHubSearchAdapter(
        api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        request_throttle=ProviderThrottle("github", requests_per_minute=0),
    )


def test_explicit_empty_key_never_falls_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SEARCH_TOKEN", "real-environment-secret")
    requests: list[httpx.Request] = []
    adapter = _adapter(
        lambda request: requests.append(request) or httpx.Response(500, request=request),
        api_key="",
    )
    with pytest.raises(ProviderUnavailableError, match="GITHUB_SEARCH_TOKEN"):
        adapter.search(SearchQuery(query="q", providers=("github",)))
    assert requests == []


def test_missing_key_fails_before_http(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SEARCH_TOKEN", raising=False)
    requests: list[httpx.Request] = []
    adapter = GitHubSearchAdapter(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(500, request=request)
            )
        ),
        request_throttle=ProviderThrottle("github", requests_per_minute=0),
    )
    with pytest.raises(ProviderUnavailableError, match="GITHUB_SEARCH_TOKEN"):
        adapter.search(SearchQuery(query="q", providers=("github",)))
    assert requests == []


def test_search_normalizes_repositories_and_caps_top_k() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json={"items": [
            {
                "full_name": "acme/agent-orchestrator",
                "html_url": "https://github.com/acme/agent-orchestrator",
                "description": "Multi-agent orchestration framework",
                "pushed_at": "2026-09-01T12:00:00Z",
                "stargazers_count": 1200,
                "forks_count": 80,
                "open_issues_count": 12,
                "language": "Python",
                "archived": False,
                "topics": ["agents", "orchestration"],
            },
            {
                "full_name": "other/repo",
                "html_url": "https://github.com/other/repo",
                "description": "second",
                "pushed_at": "2026-08-01T00:00:00Z",
                "stargazers_count": 5,
            },
        ]}, request=request)

    adapter = _adapter(handler)
    hits = adapter.search(SearchQuery(query="agent orchestration", providers=("github",), top_k=1))
    assert len(requests) == 1
    assert len(hits) == 1
    hit = hits[0]
    assert hit.provider == "github"
    assert hit.url == "https://github.com/acme/agent-orchestrator"
    assert hit.title == "acme/agent-orchestrator"
    assert hit.snippet == "Multi-agent orchestration framework"
    assert hit.publisher == "GitHub"
    assert hit.published_at is not None and hit.published_at.year == 2026
    assert hit.score_hint is None
    assert hit.raw_payload["stargazers_count"] == 1200
    assert hit.raw_payload["language"] == "Python"


def test_domain_scoping_unsupported() -> None:
    adapter = _adapter(lambda request: httpx.Response(500, request=request))
    from open_web_retrieval.exceptions import CapabilityNotSupportedError
    with pytest.raises(CapabilityNotSupportedError):
        adapter.search(SearchQuery(query="q", providers=("github",), domains_allow=["example.com"]))


def test_recency_days_adds_pushed_qualifier() -> None:
    captured_params: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json={"items": []}, request=request)

    adapter = _adapter(handler)
    adapter.search(SearchQuery(query="q", providers=("github",), recency_days=30))
    assert "pushed:>" in captured_params["q"]


def test_401_raises_provider_unavailable() -> None:
    adapter = _adapter(lambda request: httpx.Response(401, json={"message": "Bad credentials"}, request=request))
    with pytest.raises(ProviderUnavailableError, match="GITHUB_SEARCH_TOKEN"):
        adapter.search(SearchQuery(query="q", providers=("github",)))


def test_403_surfaces_github_message() -> None:
    adapter = _adapter(
        lambda request: httpx.Response(
            403, json={"message": "API rate limit exceeded"}, request=request
        )
    )
    with pytest.raises(RetrievalError, match="API rate limit exceeded"):
        adapter.search(SearchQuery(query="q", providers=("github",)))
