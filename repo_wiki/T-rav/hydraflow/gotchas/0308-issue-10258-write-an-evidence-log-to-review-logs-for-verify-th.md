---
id: 0308
topic: gotchas
source_issue: 10258
source_phase: plan
created_at: 2026-07-22T09:21:49.448742+00:00
status: superseded
corroborations: 1
superseded_by: 0310
---

# Write an evidence log to review_logs/ for verify-then-merge landing tasks

For zero-new-code landing steps (re-verify gates → merge → confirm), record `gh` command output to a per-issue file like `review_logs/issue_10258_gate_check.md`, appended at each phase (pre-merge, post-merge). This gives an auditable trail distinct from the PR/issue comment thread and survives even if GitHub state changes later.

**Why:** makes gate-check and merge evidence reviewable after the fact without re-querying GitHub or trusting agent self-report.
