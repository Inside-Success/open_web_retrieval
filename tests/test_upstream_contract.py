"""Executable checks for the public-safe downstream relationship."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))


def test_canonical_upstream_revision_is_explicit_and_immutable() -> None:
    assert MANIFEST["canonical_upstream"] == "BrianMills2718/open_web_retrieval"
    assert MANIFEST["upstream_revision"] == (
        "644ab93d210b726a4c0be82263fff6fed5f9daf8"
    )
    assert MANIFEST["accepted_source_commit"] == (
        "644ab93d210b726a4c0be82263fff6fed5f9daf8"
    )
    assert MANIFEST["relationship"] == "source_overlay_downstream"


def test_python_package_matches_accepted_upstream_snapshot() -> None:
    package_root = ROOT / "src" / "open_web_retrieval"
    digest = hashlib.sha256()
    tracked_sources = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and (path.suffix == ".py" or path.name == "py.typed")
    )
    for path in tracked_sources:
        digest.update(path.relative_to(package_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    assert digest.hexdigest() == MANIFEST["source_tree_sha256"]


def test_public_install_has_no_private_or_unrelated_runtime_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "llm-client" not in pyproject
    assert MANIFEST["runtime_dependency"] is False
    assert MANIFEST["excluded_dependencies"] == ["llm-client"]


def test_company_only_capabilities_remain_explicit_overlays() -> None:
    assert MANIFEST["downstream_only_capabilities"] == []


def test_accepted_shared_capabilities_include_openalex_and_reddit() -> None:
    assert {
        "openalex_search",
        "openalex_transient_retry",
        "openalex_agent_abstract_provenance",
        "openalex_scholarly_metadata",
        "reddit_search",
    }.issubset(
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
