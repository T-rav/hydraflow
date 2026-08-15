---
id: 1368
topic: gotchas
source_issue: 11215
source_phase: plan
created_at: 2026-08-15T05:13:01.079633+00:00
status: active
corroborations: 1
---

# Re-enter existing merge seam instead of forking a second path

When adding resume/reconcile logic that must produce the same end state as the normal path, add a public seam on the existing phase object and delegate — do not duplicate the gate sequence.

- `ReviewPhase.resume_approved_merge(pr, issue)` rebuilds a `ReviewResult(verdict=APPROVE)` and calls the existing `_handle_approved_merge`, so CI/visual/policy gates and `handle_approved`'s MERGED-idempotency guard all apply.
- Candidate selection lives in a separate `MergeResumeReconciler`; the seam stays thin.

**Why:** A second merge code path drifts from the first; the MERGED guard and post-merge hooks are load-bearing and must not be bypassed.
