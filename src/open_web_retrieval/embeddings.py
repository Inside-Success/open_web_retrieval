"""Minimal embeddings client (OpenAI-compatible endpoints, e.g. OpenRouter).

Retrieval-relevance embeddings for consumers that pre-filter fetched content
before expensive downstream processing. Deliberately tiny: one async helper,
no caching, no batching policy — callers own chunking and failure handling.
"""

from __future__ import annotations

import os

import httpx

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1/embeddings"


async def aembed_texts(
    texts: list[str],
    *,
    model: str = "openai/text-embedding-3-small",
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 30.0,
) -> list[list[float]]:
    """Embed ``texts`` via an OpenAI-compatible embeddings endpoint.

    Returns one vector per input text, in input order. Raises on any HTTP or
    shape error — callers decide whether relevance filtering is best-effort.
    """
    if not texts:
        return []
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("aembed_texts: no api_key and OPENROUTER_API_KEY unset")
    url = base_url or os.environ.get("OWR_EMBEDDINGS_BASE_URL") or _DEFAULT_BASE_URL
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError(
            f"aembed_texts: expected {len(texts)} embeddings, got "
            f"{len(data) if isinstance(data, list) else type(data).__name__}"
        )
    ordered = sorted(data, key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain cosine similarity (no numpy dependency)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
