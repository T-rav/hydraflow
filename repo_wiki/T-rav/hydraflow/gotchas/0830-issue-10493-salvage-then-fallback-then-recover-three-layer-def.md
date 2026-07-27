---
id: 0830
topic: gotchas
source_issue: 10493
source_phase: plan
created_at: 2026-07-24T23:45:36.554309+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# Salvage-then-fallback-then-recover: three-layer defense against stranded PRs

Issue #10493's fix layers three independent recovery points in `src/implement_phase.py` rather than one: (1) salvage gate on the build result — infra-reap-but-committed still pushes and opens a PR; (2) `_handle_no_pr_fallback` re-queries for a PR that `gh pr create` may have opened before dying, retries once, then persists the pending-PR marker; (3) re-pick checks the marker and recovers without rebuilding. Each layer is independently testable per `tests/regressions/test_issue_10493.py`.

**Why:** a single recovery point is a single point of failure — layering catches the reap regardless of which stage (build, PR-open, or restart) it hits.
