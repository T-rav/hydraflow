---
id: 1369
topic: gotchas
source_issue: 11215
source_phase: plan
created_at: 2026-08-15T05:13:01.079642+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# SHA-equality guard is the resume merge's load-bearing invariant

Any resume/reconcile path that re-enters `_handle_approved_merge` MUST gate on `get_pr_head_sha(pr) == state.get_last_reviewed_sha(issue)` before invoking the seam. No other check substitutes.

- Compare against `get_last_reviewed_sha`, not `last_verdict` or the ledger's own SHA field.
- Pin with explicit counter-tests in both predicate tests and the scenario layer: a PR whose head moved past the reviewed SHA is never resumed.

**Why:** Without this guard, commits pushed after review but before the resume tick land autonomously — unreviewed code merges with no operator action. This is the single worst failure mode of the feature.
