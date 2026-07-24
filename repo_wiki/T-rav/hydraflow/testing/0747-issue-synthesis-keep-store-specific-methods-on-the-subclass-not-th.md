---
id: 0747
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.444981+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# Keep store-specific methods on the subclass, not the shared ledger base

Keep store-specific methods like `AuditSampleLedger.update_dispositions` (`src/audit/store.py`) defined on the subclass rather than generalizing them into the shared `IdentifiedJsonlLedger[T]` base (`src/jsonl_ledger.py`).

Example: `update_dispositions` wasn't pulled into the base after the migration because no sibling store (`EscapeLedger`, `InterventionLedger`, `TrendStore`) needs it.

**Why:** pulling one-off, store-specific behavior into a shared base reintroduces coupling the unification was meant to remove.
