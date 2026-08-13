"""Public Jina Reader source-port contracts."""

from __future__ import annotations

import httpx
import pytest

from open_web_retrieval.adapters.jina import JinaReaderAdapter
from open_web_retrieval.exceptions import FetchError
from open_web_retrieval.models import FetchRequest

SOURCE_URL = "https://example.com/research/page"


def _response(request: httpx.Request, status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, request=request)
    return httpx.Response(
        200,
        json={"data": {"url": SOURCE_URL, "content": "# Public research"}},
        request=request,
    )


def test_jina_returns_normalized_markdown_without_credentials() -> None:
    adapter = JinaReaderAdapter(
        client=httpx.Client(transport=httpx.MockTransport(_response))
    )

    resource = adapter.fetch(FetchRequest(url=SOURCE_URL))

    assert resource.fetch_method == "jina_reader"
    assert resource.content_bytes == b"# Public research"
    assert resource.final_url == SOURCE_URL


def test_jina_optional_secret_never_enters_resource() -> None:
    adapter = JinaReaderAdapter(
        api_key="test-secret",
        client=httpx.Client(transport=httpx.MockTransport(_response)),
    )

    resource = adapter.fetch(FetchRequest(url=SOURCE_URL))

    assert "test-secret" not in resource.model_dump_json()


@pytest.mark.parametrize(("status", "retryable"), [(403, False), (429, True), (500, True)])
def test_jina_classifies_http_failures(status: int, retryable: bool) -> None:
    adapter = JinaReaderAdapter(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: _response(request, status))
        )
    )

    with pytest.raises(FetchError) as exc_info:
        adapter.fetch(FetchRequest(url=SOURCE_URL))

    assert exc_info.value.retryable is retryable


def test_jina_rejects_local_file_before_network() -> None:
    adapter = JinaReaderAdapter(
        client=httpx.Client(transport=httpx.MockTransport(_response))
    )

    with pytest.raises(FetchError) as exc_info:
        adapter.fetch(FetchRequest(url="file:///tmp/private.txt"))

    assert exc_info.value.retryable is False
