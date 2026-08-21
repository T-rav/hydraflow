---
id: 1535
topic: gotchas
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754288+00:00
status: active
corroborations: 1
---

# PRManager release tagging fails closed before any local git tag exists

The resolve step and the tag step are two methods on `PRManager` (`src/pr_manager.py`), and the resolve step runs — and can fail — before any `git tag` executes:

- `resolve_remote_branch_sha(branch)`: dry-run short-circuit → `git fetch origin +refs/heads/<b>:refs/remotes/origin/<b>` → `git rev-parse --verify --quiet refs/remotes/origin/<b>^{commit}` → full-OID check. Any `RuntimeError` (everything `_run_gh` raises subclasses it) or a non-OID answer → `logger.warning(...)` with a literal format string and `return None`.
- `create_tag(tag, *, ref)`: dry-run short-circuit → `git tag <tag> <ref>` → `git push origin <tag>`; `False` on failure. It never fetches or resolves — it only ever receives an already-verified commit SHA.
- The caller (`src/epic.py` `_create_release_for_epic`) returns before `create_tag` when the resolve yields `None`.

**Why:** a skip must leave no filesystem residue. If the fetch/rev-parse lived after `git tag`, a failure would leave an orphan local tag pointing at the wrong SHA even though the caller believed the release was skipped. Splitting resolve from tag keeps the fail-closed decision ahead of the first write.
