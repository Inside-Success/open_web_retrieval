"""Executable checks for the repository's independence declaration.

Inside-Success/open_web_retrieval was a source-overlay downstream of
BrianMills2718/open_web_retrieval until 2026-10-03. It is now the independent,
canonical Inside Success repository: nothing syncs from or contributes to the
former upstream, and the package tree may diverge from the last snapshot.
UPSTREAM.json keeps the former relationship as history only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))
FORMER = MANIFEST["former_upstream"]


def test_company_repository_is_independent_and_canonical() -> None:
    assert MANIFEST["schema_version"] == 2
    assert MANIFEST["repository_role"] == "inside_success_independent_canonical"
    assert MANIFEST["company_repository"] == "Inside-Success/open_web_retrieval"
    assert MANIFEST["canonical_repository"] == "Inside-Success/open_web_retrieval"
    assert MANIFEST["canonical_upstream"] is None


def test_no_sync_or_upstream_contribution_route_remains() -> None:
    sync = MANIFEST["sync"]
    assert sync["direction"] == "none"
    assert sync["upstream_contributions"] == "none"
    assert sync["company_changes_allowed"] is True
    assert sync["source_parity_required"] is False
    assert "sync_rules" not in MANIFEST
    # No live field outside the history block may name the former upstream.
    live = {key: value for key, value in MANIFEST.items() if key != "former_upstream"}
    assert "BrianMills2718" not in json.dumps(live)


def test_former_upstream_history_is_preserved() -> None:
    assert FORMER["repository"] == "BrianMills2718/open_web_retrieval"
    assert FORMER["relationship"] == "source_overlay_downstream"
    assert FORMER["last_integrated_commit"] == (
        "763c6ea3cc4e1b65dc0fc62ab293a759e2d52385"
    )
    assert FORMER["accepted_source_commit"] == FORMER["last_integrated_commit"]
    assert re.fullmatch(r"[0-9a-f]{64}", FORMER["source_tree_sha256_at_last_integration"])
    assert FORMER["upstream_version_at_last_integration"] == "0.14.0"
    assert FORMER["disconnected_on"] == "2026-10-03"
    assert "left Inside Success" in FORMER["reason"]


def test_public_install_has_no_private_or_unrelated_runtime_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "llm-client" not in pyproject
    assert "brianmills2718" not in pyproject
    assert MANIFEST["runtime_dependency"] is False
    assert MANIFEST["excluded_dependencies"] == ["llm-client"]


def test_capabilities_accepted_before_disconnection_are_recorded() -> None:
    assert {
        "openalex_search",
        "openalex_transient_retry",
        "openalex_agent_abstract_provenance",
        "reddit_search",
        "jina_reader_fetch",
        "access_challenge_fallback",
        "typed_access_alternatives",
        "access_block_classifier",
        "x_search",
        "github_search",
    }.issubset(FORMER["accepted_shared_capabilities"])
