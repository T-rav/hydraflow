---
id: 0147
topic: architecture
source_issue: 10258
source_phase: plan
created_at: 2026-07-22T09:21:49.448712+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Re-verify PR gate state at merge time, not just at plan time

CI/head state can drift between planning and execution — treat plan-time checks as stale. Before merging, re-run `gh pr view <PR> --json state,mergeable,mergeStateStatus,headRefOid` and `gh pr checks <PR>` to confirm the head SHA hasn't moved and all required checks (e.g. the full `Tests` job) are still green. This pattern was used landing PR #10256 for issue #10258, pinning head `273712c9` immediately before `gh pr merge --squash`. A red check found here means STOP — no merge, comment findings on the issue, reopen diagnosis instead of proceeding on stale evidence.

**Why:** merging on stale gate evidence can land code past a check that went red after planning but before execution.
