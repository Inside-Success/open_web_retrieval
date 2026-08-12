"""Accepted upstream OpenAlex keyword, semantic, and OQL contract."""

from __future__ import annotations

import json

import httpx
import pytest

from open_web_retrieval.adapters.openalex import OpenAlexSearchAdapter
from open_web_retrieval.exceptions import RetrievalError
from open_web_retrieval.models import OpenAlexQuery


def _result() -> dict[str, object]:
    return {
        "id": "https://openalex.org/W1",
        "title": "Conspiracy drivers online",
        "publication_date": "2024-01-02",
        "best_oa_location": {"pdf_url": "https://papers.example/1.pdf"},
        "primary_location": {"source": {"display_name": "Research Journal"}},
        "abstract_inverted_index": {"Conspiracy": [0], "drivers": [1]},
    }


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"meta": {"cost_usd": 0.001}, "results": [_result()]},
            request=request,
        )


def _adapter(recorder: Recorder, *, api_key: str | None = None) -> OpenAlexSearchAdapter:
    return OpenAlexSearchAdapter(
        api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(recorder)),
    )


def test_semantic_mode_uses_native_parameter_and_normalizes_provenance() -> None:
    recorder = Recorder()
    hit = _adapter(recorder).search(
        OpenAlexQuery(query="why people share conspiracies", mode="semantic", top_k=1)
    )[0]

    assert recorder.requests[0].url.params["search.semantic"] == (
        "why people share conspiracies"
    )
    assert hit.provider == "openalex"
    assert hit.raw_payload is not None
    assert hit.raw_payload["_openalex_meta"]["mode"] == "semantic"


def test_oql_posts_works_query_unchanged() -> None:
    recorder = Recorder()
    query = "works where title/abstract has (conspiracy drivers) and year >= (2020)"
    _adapter(recorder).search(OpenAlexQuery(query=query, mode="oql", top_k=1))

    request = recorder.requests[0]
    assert request.method == "POST"
    assert json.loads(request.content)["oql"] == query


def test_api_key_uses_bearer_header_not_url() -> None:
    recorder = Recorder()
    _adapter(recorder, api_key="test-secret").search(OpenAlexQuery(query="q"))
    request = recorder.requests[0]
    assert request.headers["authorization"] == "Bearer test-secret"
    assert "test-secret" not in str(request.url)


def test_invalid_response_shape_fails_loudly() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"results": {}}, request=request)
    )
    adapter = OpenAlexSearchAdapter(client=httpx.Client(transport=transport))
    with pytest.raises(RetrievalError, match="results list"):
        adapter.search(OpenAlexQuery(query="q"))


@pytest.mark.parametrize(
    "query",
    ["authors where works_count > (10)", "works where year is (2024) group by type"],
)
def test_oql_rejects_non_hit_shapes_before_http(query: str) -> None:
    recorder = Recorder()
    with pytest.raises(ValueError):
        _adapter(recorder).search(OpenAlexQuery(query=query, mode="oql"))
    assert recorder.requests == []
