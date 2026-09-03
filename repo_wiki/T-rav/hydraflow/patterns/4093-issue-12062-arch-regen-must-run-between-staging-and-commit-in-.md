---
id: 4093
topic: patterns
source_issue: 12062
source_phase: plan
created_at: 2026-09-02T22:21:22.693478+00:00
status: active
corroborations: 1
---

# Arch regen must run between staging and commit in bot PR finalize

Call arch-regen in `_finalize_pr_from_worktree` (src/auto_pr.py:779) after the no-diff short-circuit and before `_run_preflight_gate` (src/auto_pr.py:829). Placement ensures pre-commit hook passes and preflight `arch` stage un-reds. Apply via `subprocess_util.run_subprocess` with `cwd=worktree_path`, `timeout=_ARCH_REGEN_TIMEOUT_S`, `gh_token` threaded through.
