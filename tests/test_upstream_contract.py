"""Executable checks for the public-safe downstream relationship."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_canonical_upstream_revision_is_explicit_and_immutable() -> None:
    assert MANIFEST["canonical_upstream"] == "BrianMills2718/open_web_retrieval"
    assert MANIFEST["upstream_revision"] == (
        "402d0d4f575ff6df600f6ee63b15b013d16b0e84"
    )
    assert MANIFEST["accepted_source_commit"] == (
        "1b0dcd60c17ff3fb7520b8a8da88c1696248e662"
    )
    assert MANIFEST["relationship"] == "source_overlay_downstream"


def test_public_install_has_no_private_or_unrelated_runtime_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "llm-client" not in pyproject
    assert MANIFEST["runtime_dependency"] is False
    assert MANIFEST["excluded_dependencies"] == ["llm-client"]


def test_company_only_capabilities_remain_explicit_overlays() -> None:
    assert set(MANIFEST["downstream_only_capabilities"]) == {
        "embeddings_helpers",
    }


def test_accepted_shared_capabilities_include_openalex_and_reddit() -> None:
    assert {"openalex_search", "reddit_search"}.issubset(
        MANIFEST["accepted_shared_capabilities"]
    )
    assert MANIFEST["upstream_version"] == "0.11.0"
