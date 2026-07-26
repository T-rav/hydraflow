---
id: 0934
topic: gotchas
source_issue: 10555
source_phase: plan
created_at: 2026-07-25T22:52:11.067257+00:00
status: superseded
corroborations: 1
superseded_by: 0940
---

# Key review-tier triggers off issue labels, not PR labels — `PRPort` has no `get_pr_labels`

`PRPort` exposes `post_pr_comment` but no label-read method; label-gated triggers (e.g. a `review:ultra` opt-in) must read via `IssueStorePort.get_issue_labels` on the linked issue instead of extending `PRPort`.

**Why:** avoids an unnecessary Port surface expansion when the existing issue-side read already satisfies the gate.
