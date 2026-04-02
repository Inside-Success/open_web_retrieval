# Operational Knowledge — open_web_retrieval

Shared findings from all agent sessions. Any agent brain can read and append.
Human-reviewed periodically.

## Findings

<!-- Append new findings below this line. Do not overwrite existing entries. -->
<!-- Format: ### YYYY-MM-DD — {agent} — {category}                          -->
<!-- Categories: bug-pattern, performance, schema-gotcha, integration-issue, -->
<!--             workaround, best-practice                                   -->
<!-- Agent names: claude-code, codex, openclaw                               -->

---

### 2026-04-01 — codex — best-practice

`install_governed_repo.py` can overreach for ownership-only or baseline-plus-
ownership waves by adding sanctioned-worktree entrypoints even when the repo's
policy keeps worktrees disabled. Treat installer output as bounded input, not as
an unconditional truth surface: keep the mechanical governance helpers that help
the current wave, and revert worktree entrypoints unless the plan explicitly
adopts sanctioned worktrees.

### 2026-04-02 — codex — integration-issue

Authoritative coordination rollout has two distinct claim layers: the shared
coordination registry (`scripts/meta/check_coordination_claims.py`) and the
repo-local worktree registry (`scripts/meta/worktree-coordination/check_claims.py`).
Installing the sanctioned scripts is not enough by itself; a repo-local
worktree claim must also exist before `make worktree-list` reports the active
worktree truthfully instead of `ACTIVE (no claim)`.

### 2026-04-02 — codex — best-practice

Repo-local coordination runtime state lives under `.claude/` and should be ignored at the repo boundary. Otherwise a successful claim/reservation rollout leaves the canonical repo artificially dirty with local-only session and claim files.
