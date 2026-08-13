"""Pure discovery of advisory routes for blocked public resources."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

from open_web_retrieval.exceptions import FetchBlockReason
from open_web_retrieval.fetch_extract import _detect_access_block_payload
from open_web_retrieval.models import (
    AccessAlternative,
    AccessAlternativeKind,
    FetchedResource,
)

_ARXIV_PATH = re.compile(
    r"^/(?:abs|pdf)/"
    r"((?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?)(?:\.pdf)?$"
)
_HN_PATH = re.compile(r"^/item$")
_REDDIT_PATH = re.compile(r"^/(?:r/[^/]+/)?comments/([a-z0-9]+)(?:/|$)", re.IGNORECASE)
_GITHUB_ISSUE_PATH = re.compile(r"^/([^/]+)/([^/]+)/issues/(\d+)(?:/|$)")
_GITHUB_BLOB_PATH = re.compile(
    r"^/([^/]+)/([^/]+)/blob/([0-9a-fA-F]{40})/(.+)$"
)


def classify_access_block(resource: FetchedResource) -> FetchBlockReason | None:
    """Classify a normalized fetch payload using the canonical block policy."""

    return _detect_access_block_payload(
        status=resource.status,
        content_type=resource.content_type,
        content=resource.content_bytes,
    )


def _alternative(
    *,
    source_url: str,
    route_url: str,
    kind: AccessAlternativeKind,
    provider: str,
    rationale: str,
    requirements: tuple[str, ...] = (),
) -> AccessAlternative:
    return AccessAlternative(
        source_url=source_url,
        route_url=route_url,
        kind=kind,
        provider=provider,
        requirements=requirements,
        rationale=rationale,
    )


def suggest_access_alternatives(
    source_url: str,
    block_reason: FetchBlockReason,
) -> tuple[AccessAlternative, ...]:
    """Return deterministic alternatives without performing network I/O."""

    parsed = urlsplit(source_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ()

    clean_source = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    host = parsed.hostname.lower().removeprefix("www.")
    alternatives: list[AccessAlternative] = []

    if host in {"arxiv.org", "export.arxiv.org"}:
        match = _ARXIV_PATH.match(parsed.path)
        if match:
            arxiv_id = match.group(1)
            alternatives.append(_alternative(
                source_url=clean_source,
                route_url=f"https://export.arxiv.org/api/query?id_list={quote(arxiv_id, safe='.')}",
                kind="official_api",
                provider="arxiv",
                rationale="Retrieve the same paper record through the official arXiv API.",
            ))

    if host == "news.ycombinator.com" and _HN_PATH.match(parsed.path):
        item_id = next((value for key, value in _query_pairs(parsed.query) if key == "id"), None)
        if item_id and item_id.isdigit():
            hn_source = f"{clean_source}?id={item_id}"
            alternatives.append(_alternative(
                source_url=hn_source,
                route_url=f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
                kind="official_api",
                provider="hackernews",
                rationale="Retrieve the same item through the official Hacker News Firebase API.",
            ))

    if host in {"reddit.com", "old.reddit.com"}:
        match = _REDDIT_PATH.match(parsed.path)
        if match:
            alternatives.append(_alternative(
                source_url=clean_source,
                route_url=f"https://oauth.reddit.com/comments/{match.group(1)}",
                kind="official_api",
                provider="reddit",
                requirements=("reddit_oauth",),
                rationale="Retrieve the same discussion through Reddit's OAuth API.",
            ))

    if host == "github.com":
        issue_match = _GITHUB_ISSUE_PATH.match(parsed.path)
        blob_match = _GITHUB_BLOB_PATH.match(parsed.path)
        if issue_match:
            owner, repository, number = issue_match.groups()
            alternatives.append(_alternative(
                source_url=clean_source,
                route_url=f"https://api.github.com/repos/{owner}/{repository}/issues/{number}",
                kind="official_api",
                provider="github",
                rationale="Retrieve the same issue or pull request through the GitHub API.",
                requirements=("github_token_for_private_or_rate_limited_content",),
            ))
        elif blob_match:
            owner, repository, revision, path = blob_match.groups()
            alternatives.append(_alternative(
                source_url=clean_source,
                route_url=f"https://raw.githubusercontent.com/{owner}/{repository}/{revision}/{path}",
                kind="official_raw",
                provider="github",
                rationale="Retrieve the same repository file through GitHub's raw-content route.",
            ))

    safe_for_reader = (
        block_reason != "captcha_required"
        and not parsed.query
    )
    if safe_for_reader:
        alternatives.append(_alternative(
            source_url=clean_source,
            route_url=f"https://r.jina.ai/{clean_source}",
            kind="hosted_reader",
            provider="jina_reader",
            rationale="Ask the configured hosted reader for a public representation of the same URL.",
            requirements=("discloses_target_url_to_jina",),
        ))

    return tuple(alternatives)


def _query_pairs(query: str) -> tuple[tuple[str, str], ...]:
    """Parse a small query without expanding unrelated URL semantics."""

    pairs = []
    for item in query.split("&"):
        key, separator, value = item.partition("=")
        if separator:
            pairs.append((key, value))
    return tuple(pairs)
