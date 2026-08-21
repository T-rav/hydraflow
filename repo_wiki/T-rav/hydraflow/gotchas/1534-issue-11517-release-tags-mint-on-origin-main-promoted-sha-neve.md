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

Release-minting code must tag the RC-gated promoted SHA `origin/{main_branch}` (ADR-0042), never the factory checkout `HEAD`.

- `src/epic.py` `_create_release_for_epic` passes `ref=f"origin/{self._config.main_branch}"` explicitly to `PRManager.create_tag` (`src/pr_manager.py`).
- Unresolvable main → skip the release entirely, no tag (ADR-0011 fail-closed).

**Why:** the factory checkout HEAD is `staging` or a mid-work agent worktree branch; a bare tag there mints a release on unreleased code (#11517 — latent, no tag had ever been cut by this path).
