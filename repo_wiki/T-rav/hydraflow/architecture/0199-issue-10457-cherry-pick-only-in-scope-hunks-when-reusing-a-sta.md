---
id: 0199
topic: architecture
source_issue: 10457
source_phase: plan
created_at: 2026-07-24T12:45:53.971873+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Cherry-pick only in-scope hunks when reusing a stalled reference commit

ADR-drift work often has a prior reference implementation on a stalled branch (e.g. `agent/issue-10411` commit `92c9a12c`) bundling multiple concerns. When reusing it for a new issue (e.g. #10457's fleet auto-close), explicitly exclude unrelated hunks from the same commit — it also touched `_SHARED_INFRA_MODULES` allowlisting and a churn-threshold, both separate issues. State excluded hunks in the plan's Key Considerations so reviewers see scope was deliberately trimmed.

**Why:** Pulling a whole reference commit inflates the diff, draws review fire onto unrelated changes, and re-mixes concerns split into separate issues.
