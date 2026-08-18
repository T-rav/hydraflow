---
id: 1490
topic: gotchas
source_issue: 11418
source_phase: plan
created_at: 2026-08-18T03:42:49.483161+00:00
status: active
corroborations: 1
---

# Ban PRPort reach-through via architecture tests

Enforce `PRPort` boundaries by banning direct access to `_run_gh` and `_repo` outside `src/pr_manager*.py`. Use `tests/architecture/test_pr_port_no_reach_through.py` to fail if loops like `src/stale_issue_loop.py` bypass the Port.

**Why:** Prevents string-matching dispatcher divergence (root cause of #11413/#11419) by forcing all GitHub reads through declared Protocol methods with cassette-backed coverage.
