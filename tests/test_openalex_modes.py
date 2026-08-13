"""Accepted upstream OpenAlex keyword, semantic, and OQL contract."""

from __future__ import annotations

import json

import httpx
import pytest

from open_web_retrieval.adapters.base import ProviderThrottle
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
    def __init__(self, *, statuses: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(
            status,
            json={"meta": {"cost_usd": 0.001}, "results": [_result()]},
            request=request,
        )


def _adapter(recorder: Recorder, *, api_key: str | None = None) -> OpenAlexSearchAdapter:
    return OpenAlexSearchAdapter(
        api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(recorder)),
        request_throttle=ProviderThrottle("openalex", requests_per_minute=0),
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


def test_transient_504_retries_identical_query_once_then_succeeds() -> None:
    recorder = Recorder(statuses=[504, 200])

    hits = _adapter(recorder).search(
        OpenAlexQuery(query="conspiracy sharing motives", mode="semantic", top_k=1)
    )

    assert len(recorder.requests) == 2
    assert recorder.requests[0].url == recorder.requests[1].url
    assert hits[0].provider == "openalex"


def test_persistent_504_stops_after_one_retry() -> None:
    recorder = Recorder(statuses=[504, 504])

    with pytest.raises(RetrievalError) as exc_info:
        _adapter(recorder).search(OpenAlexQuery(query="q", mode="semantic"))

    assert len(recorder.requests) == 2
    assert exc_info.value.context["status_code"] == 504


def test_non_transient_400_is_not_retried() -> None:
    recorder = Recorder(statuses=[400])

    with pytest.raises(RetrievalError):
        _adapter(recorder).search(OpenAlexQuery(query="q"))

    assert len(recorder.requests) == 1


@pytest.mark.parametrize("retries", [-1, 4])
def test_retry_bound_rejects_invalid_values(retries: int) -> None:
    with pytest.raises(ValueError, match="max_transient_retries"):
        OpenAlexSearchAdapter(max_transient_retries=retries)


@pytest.mark.parametrize(
    "query",
    ["authors where works_count > (10)", "works where year is (2024) group by type"],
)
def test_oql_rejects_non_hit_shapes_before_http(query: str) -> None:
    recorder = Recorder()
    with pytest.raises(ValueError):
        _adapter(recorder).search(OpenAlexQuery(query=query, mode="oql"))
    assert recorder.requests == []
