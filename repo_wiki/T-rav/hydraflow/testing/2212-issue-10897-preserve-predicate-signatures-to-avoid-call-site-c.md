---
id: 2212
topic: testing
source_issue: 10897
source_phase: plan
created_at: 2026-07-31T12:53:03.086174+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Preserve predicate signatures to avoid call-site churn

When changing `is_self_chore_change`'s body from subject-only to subject+scope, keep its `(change)` signature intact. `MergedChange` already carries `changed_paths`, so no new parameter is needed. `sampled_audit_loop` and other callers require zero changes. **Why:** Signature changes ripple through consumers and regression tests, increasing blast radius of a logic-only fix.
