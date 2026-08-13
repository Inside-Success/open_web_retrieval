"""Contract tests for advisory blocked-fetch alternatives."""

import hashlib
from datetime import datetime, timezone

import httpx
import pytest

from open_web_retrieval import (
    FetchedResource,
    FetchError,
    FetchRequest,
    SourceFetcher,
    classify_access_block,
    suggest_access_alternatives,
)


def _resource(*, status=200, content=b"ordinary article"):
    return FetchedResource(
        requested_url="https://example.com",
        final_url="https://example.com",
        status=status,
        content_type="text/markdown",
        content_bytes=content,
        retrieved_at_utc=datetime.now(timezone.utc),
        sha256=hashlib.sha256(content).hexdigest(),
    )


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        (_resource(), None),
        (_resource(status=403), "access_denied"),
        (_resource(content=b"Just a moment... checking your browser"), "challenge_detected"),
        (_resource(content=b"Please verify you are human"), "captcha_required"),
    ],
)
def test_public_access_block_classifier_matches_fetch_policy(resource, expected):
    assert classify_access_block(resource) == expected


@pytest.mark.parametrize(
    ("url", "provider", "route_url"),
    [
        (
            "https://arxiv.org/abs/2401.12345",
            "arxiv",
            "https://export.arxiv.org/api/query?id_list=2401.12345",
        ),
        (
            "https://news.ycombinator.com/item?id=12345",
            "hackernews",
            "https://hacker-news.firebaseio.com/v0/item/12345.json",
        ),
        (
            "https://www.reddit.com/r/research/comments/abc123/a_post/",
            "reddit",
            "https://oauth.reddit.com/comments/abc123",
        ),
        (
            "https://github.com/acme/project/issues/42",
            "github",
            "https://api.github.com/repos/acme/project/issues/42",
        ),
        (
            "https://github.com/acme/project/blob/0123456789abcdef0123456789abcdef01234567/docs/readme.md",
            "github",
            "https://raw.githubusercontent.com/acme/project/0123456789abcdef0123456789abcdef01234567/docs/readme.md",
        ),
    ],
)
def test_known_official_alternative(url, provider, route_url):
    alternatives = suggest_access_alternatives(url, "access_denied")
    match = next(item for item in alternatives if item.provider == provider)
    assert match.route_url == route_url
    assert match.source_url == url
    assert match.automatic is False


def test_clean_public_challenge_suggests_advisory_jina_reader():
    alternatives = suggest_access_alternatives(
        "https://example.com/article",
        "challenge_detected",
    )
    assert [item.provider for item in alternatives] == ["jina_reader"]
    assert alternatives[0].requirements == ("discloses_target_url_to_jina",)


def test_legacy_arxiv_identifier_maps_to_official_api():
    alternatives = suggest_access_alternatives(
        "https://arxiv.org/abs/hep-th/9901001v2",
        "access_denied",
    )
    assert alternatives[0].route_url == (
        "https://export.arxiv.org/api/query?id_list=hep-th%2F9901001v2"
    )


def test_named_github_revision_is_not_guessed_as_raw_route():
    alternatives = suggest_access_alternatives(
        "https://github.com/acme/project/blob/feature/docs/readme.md",
        "captcha_required",
    )
    assert alternatives == ()


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/article",
        "https://example.com/article?token=secret",
    ],
)
def test_sensitive_url_does_not_suggest_hosted_reader(url):
    assert suggest_access_alternatives(url, "challenge_detected") == ()


def test_known_route_does_not_copy_unrelated_query_values():
    alternatives = suggest_access_alternatives(
        "https://news.ycombinator.com/item?id=12345&token=secret",
        "access_denied",
    )
    assert [item.provider for item in alternatives] == ["hackernews"]
    assert alternatives[0].source_url == "https://news.ycombinator.com/item?id=12345"
    assert "secret" not in alternatives[0].model_dump_json()


def test_captcha_never_suggests_hosted_reader():
    alternatives = suggest_access_alternatives(
        "https://arxiv.org/abs/2401.12345",
        "captcha_required",
    )
    assert [item.provider for item in alternatives] == ["arxiv"]


def test_blocked_fetch_exposes_alternatives_without_executing_them():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            403,
            text="Access denied",
            headers={"content-type": "text/html"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        SourceFetcher(client=client, rate_limit_per_second=0) as fetcher,
        pytest.raises(FetchError) as exc_info,
    ):
        fetcher.fetch(FetchRequest(url="https://news.ycombinator.com/item?id=12345"))

    error = exc_info.value
    assert requests == ["https://news.ycombinator.com/item?id=12345"]
    assert error.retryable is False
    assert error.block_reason == "access_denied"
    assert error.alternatives[0].provider == "hackernews"
    assert error.context["alternatives"][0]["automatic"] is False


def test_non_access_fetch_error_has_no_alternatives():
    error = FetchError("connection failed", retryable=True)
    assert error.alternatives == ()
    assert "alternatives" not in error.context
