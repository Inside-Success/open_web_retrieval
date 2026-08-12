"""Executable checks for the public-safe downstream relationship."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_canonical_upstream_revision_is_explicit_and_immutable() -> None:
    assert MANIFEST["canonical_upstream"] == "BrianMills2718/open_web_retrieval"
    assert MANIFEST["upstream_revision"] == (
        "cd29613c424d9ba9a119fa18af762f218b1b82ea"
    )
    assert MANIFEST["accepted_source_commit"] == (
        "6d177d3d7d393110f9dc6526d447073f2f57c0b3"
    )
    assert MANIFEST["relationship"] == "source_overlay_downstream"


def test_public_install_has_no_private_or_unrelated_runtime_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "llm-client" not in pyproject
    assert MANIFEST["runtime_dependency"] is False
    assert MANIFEST["excluded_dependencies"] == ["llm-client"]


def test_company_only_capabilities_remain_explicit_overlays() -> None:
    assert set(MANIFEST["downstream_only_capabilities"]) == {
        "reddit_search",
        "openalex_search",
        "embeddings_helpers",
    }
