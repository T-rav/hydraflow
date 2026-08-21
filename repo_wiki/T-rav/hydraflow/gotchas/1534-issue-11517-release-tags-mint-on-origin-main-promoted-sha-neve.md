---
id: 1534
topic: gotchas
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754244+00:00
status: active
corroborations: 1
---

# Release tags mint on origin/main promoted SHA, never factory checkout HEAD

Release-minting code must tag the RC-gated promoted SHA of `origin/{main_branch}` (ADR-0042), never the factory checkout `HEAD`.

- `src/epic.py` `_create_release_for_epic` first calls `PRManager.resolve_remote_branch_sha(self._config.main_branch)` (`src/pr_manager.py`) — `git fetch origin +refs/heads/<b>:refs/remotes/origin/<b>` then `git rev-parse --verify --quiet refs/remotes/origin/<b>^{commit}`, checked against the full-OID regex — and passes the **resolved commit SHA** as `ref=` to `PRManager.create_tag(tag, *, ref)`. It does not pass the symbolic `origin/<b>` string: a symbolic ref would tag whatever the *local* remote-tracking ref held, which is stale without the fetch.
- Unresolvable main (`None`) → skip the release entirely, no tag, changelog preserved for the caller (ADR-0011 fail-closed).

**Why:** the factory checkout HEAD is `staging` or a mid-work agent worktree branch; a bare tag there mints a release on unreleased code (#11517 — latent, no tag had ever been cut by this path). Pinned by `tests/regressions/test_issue_11517.py`, which builds a repo where `HEAD`, the stale local `origin/main`, and the promoted remote `main` are three different commits.
