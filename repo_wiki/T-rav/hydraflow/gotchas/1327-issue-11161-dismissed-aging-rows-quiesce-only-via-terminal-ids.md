---
id: 1327
topic: gotchas
source_issue: 11161
source_phase: plan
created_at: 2026-08-14T18:36:34.319401+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# DISMISSED aging rows quiesce only via terminal_ids + dismissal reconcile

`DISMISSED` on aging never writes `encoded_as`, so quiescence depends entirely on two mechanisms working together.

- `terminal_ids` exclusion (#11137/#11144) prevents re-firing on the same issue number.
- The dismissal reconcile (#11148) closes the surfaced issue.
- If either regresses, the surface re-fires under a new issue number with no `encoded_as` to stop it.

**Why:** Without `encoded_as`, there is no self-answered predicate to break the loop — only the exclusion + reconcile chain prevents infinite re-surfacing.
