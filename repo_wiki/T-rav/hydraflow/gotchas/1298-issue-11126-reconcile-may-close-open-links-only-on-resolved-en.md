---
id: 1298
topic: gotchas
source_issue: 11126
source_phase: plan
created_at: 2026-08-14T11:53:15.166025+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Reconcile may close open links only on RESOLVED_ENCODED with evidence path

When diagnosing escapes behind OPEN links in `_reconcile_surfaced_issues`, only `RESOLVED_ENCODED` may trigger a close, and the close comment must name the specific evidence file path.

- Prevents mass-closing stranded issues on a false `regression_hits` grep match (e.g., an unrelated `tests/` file citing the issue number).
- Diagnosis failure during reconcile must leave the link open — no close on error.

**Why:** A false-positive grep on issue numbers in `tests/` would auto-close genuinely open escapes with no human review.
