---
id: 1532
topic: gotchas
source_issue: 11507
source_phase: plan
created_at: 2026-08-21T02:19:43.269824+00:00
status: active
corroborations: 1
---

# Fail-closed on git errors in landed-work guard

`_worktree_has_unlanded_work` must return True (unlanded → skip collection) when `run_subprocess` raises `RuntimeError` or `OSError`, including the case where `origin/<base>` has been deleted.

- `(path / ".git").exists()` is False → return False (collectable). Load-bearing: phase-2 tests build plain `issue-N` dirs and assert `destroy` IS awaited.
- Otherwise run the two-dot diff via the existing `run_subprocess` (with `base = self._config.base_branch()`, `gh_token=self._credentials.gh_token`).

**Why:** Failing open would reap worktrees on transient git errors, destroying work; failing closed preserves data at the cost of a missed collection cycle.
