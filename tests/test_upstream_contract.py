"""Executable checks for the public-safe downstream relationship."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_canonical_upstream_revision_is_explicit_and_immutable() -> None:
    assert MANIFEST["canonical_upstream"] == "BrianMills2718/open_web_retrieval"
    assert MANIFEST["upstream_revision"] == (
        "0d555aad9401fac8d66b5ee7af80379614721f5a"
    )
    assert MANIFEST["accepted_source_commit"] == (
        "81a934297b7822e9ef1ee3c94e368b23f8129ed1"
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
    assert {"jina_reader_fetch", "access_challenge_fallback"}.issubset(
        MANIFEST["accepted_shared_capabilities"]
    )
