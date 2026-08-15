---
id: 2422
topic: patterns
source_issue: 11215
source_phase: plan
created_at: 2026-08-15T05:13:01.079608+00:00
status: active
corroborations: 1
---

# Convergence ledger persistence as a cross-restart signal

A `ConvergenceLedger` row that exists with `converged=True` is the durable signal that `_handle_approved_merge` never finished — `clear_convergence_ledger` fires only post-merge. Treat it as the canonical "merge step incomplete" marker for any resume/reconciliation logic, not `StateData.last_reviewed_sha` alone.

- `_flow_post_review` writes the ledger, `_flow_gate` flips `converged`, `_handle_approved_merge` clears it.
- A crashed factory between those steps leaves the ledger stranded, not the PR state.

**Why:** Relying on PR labels or review state alone misses the exact orphan window; the ledger is the only write that straddles the crash boundary.
