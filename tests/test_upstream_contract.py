"""Executable checks for the public-safe downstream relationship."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_canonical_upstream_revision_is_explicit_and_immutable() -> None:
    assert MANIFEST["canonical_upstream"] == "BrianMills2718/open_web_retrieval"
    assert MANIFEST["upstream_revision"] == (
        "42c8e5c67724551019ca9fa9cf74c2e5b31e011f"
    )
    assert MANIFEST["accepted_source_commit"] == (
        "a883d6a3928b83d59aad027c1be7a3a83c934c7c"
    )
    assert MANIFEST["relationship"] == "source_overlay_downstream"


def test_public_install_has_no_private_or_unrelated_runtime_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "llm-client" not in pyproject
    assert MANIFEST["runtime_dependency"] is False
    assert MANIFEST["excluded_dependencies"] == ["llm-client"]


def test_company_only_capabilities_remain_explicit_overlays() -> None:
    assert MANIFEST["downstream_only_capabilities"] == []


def test_accepted_shared_capabilities_include_openalex_and_reddit() -> None:
    assert {"openalex_search", "reddit_search"}.issubset(
        MANIFEST["accepted_shared_capabilities"]
    )
    assert MANIFEST["upstream_version"] == "0.12.0"


def test_access_challenge_contract_is_accepted_shared_infrastructure() -> None:
    assert {
        "jina_reader_fetch",
        "access_challenge_fallback",
        "typed_access_alternatives",
        "access_block_classifier",
    }.issubset(
        MANIFEST["accepted_shared_capabilities"]
    )
