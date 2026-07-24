---
id: 0629
topic: testing
source_issue: 10403
source_phase: plan
created_at: 2026-07-24T05:36:17.563779+00:00
status: active
corroborations: 1
---

# Keep store-specific methods on the subclass, not the shared ledger base

`AuditSampleLedger.update_dispositions` (in `src/audit/store.py`) stays defined on the subclass even after migrating to `IdentifiedJsonlLedger[T]` in `src/jsonl_ledger.py` — it isn't generalized into the base because no sibling store (`EscapeLedger`, `InterventionLedger`, `TrendStore`) needs it.

**Why:** pulling one-off, store-specific behavior into a shared base reintroduces coupling the unification was meant to remove.
