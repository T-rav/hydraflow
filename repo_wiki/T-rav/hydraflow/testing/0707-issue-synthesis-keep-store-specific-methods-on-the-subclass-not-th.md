---
id: 0707
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.886715+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# Keep store-specific methods on the subclass, not the shared ledger base

Keep store-specific methods like `AuditSampleLedger.update_dispositions` (`src/audit/store.py`) defined on the subclass rather than generalizing them into the shared `IdentifiedJsonlLedger[T]` base (`src/jsonl_ledger.py`).

Example: `update_dispositions` wasn't pulled into the base after the migration because no sibling store (`EscapeLedger`, `InterventionLedger`, `TrendStore`) needs it.

**Why:** pulling one-off, store-specific behavior into a shared base reintroduces coupling the unification was meant to remove.
