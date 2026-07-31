---
id: 1245
topic: gotchas
source_issue: 10882
source_phase: plan
created_at: 2026-07-31T12:09:08.255873+00:00
status: active
corroborations: 1
---

# SKIPPED checks pass branch protection — guard the promotion merge path

When the RC gate skips (`should_run=false`), branch protection sees SKIPPED checks as passing, so `wait_for_ci` treats the state as green. The promotion loop in `tests/scenarios/test_rebase_on_conflict_scenario.py` must still attempt `update_pr_branch` + re-poll + retry on merge conflict, and never return `promoted` without a successful merge.

- P3 scenario: RC gate skipped → `wait_for_ci` sees SKIPPED-only as passing → first merge fails on conflict → `update_pr_branch` + re-poll + retry → loop never returns `promoted` without merge success.

**Why:** A skipped gate can let a CONFLICTING PR through to merge if the promotion path doesn't independently verify mergeability.
