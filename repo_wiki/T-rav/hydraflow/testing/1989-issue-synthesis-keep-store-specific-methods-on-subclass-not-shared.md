---
id: 1989
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.255201+00:00
status: superseded
corroborations: 1
supersedes: 1862
superseded_by: 2119
---

# Keep store-specific methods on subclass, not shared base

Keep store-specific methods like AuditSampleLedger.update_dispositions (src/audit/store.py) defined on the subclass rather than generalizing them into the shared IdentifiedJsonlLedger[T] base (src/jsonl_ledger.py).

Example: update_dispositions wasn't pulled into the base because no sibling store (EscapeLedger, InterventionLedger, TrendStore) needs it.

**Why:** Pulling one-off, store-specific behavior into a shared base reintroduces coupling the unification was meant to remove.
