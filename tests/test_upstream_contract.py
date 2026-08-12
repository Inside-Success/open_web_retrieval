"""Executable checks for the public-safe downstream relationship."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_canonical_upstream_revision_is_explicit_and_immutable() -> None:
    assert MANIFEST["canonical_upstream"] == "BrianMills2718/open_web_retrieval"
    assert MANIFEST["upstream_revision"] == (
        "ea48b5d1a720a4b67ba365ac30ca62b5596aed8a"
    )
    assert MANIFEST["accepted_source_commit"] == (
        "9ba4fe5dffb103af28566393fc38cf67af5d71a9"
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
        "embeddings_helpers",
    }


def test_openalex_is_an_accepted_shared_capability() -> None:
    assert "openalex_search" in MANIFEST["accepted_shared_capabilities"]
    assert MANIFEST["upstream_version"] == "0.10.0"
