---
id: 0833
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.212676+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# Keep store-specific methods on the subclass, not the shared ledger base

Keep store-specific methods like `AuditSampleLedger.update_dispositions` (`src/audit/store.py`) defined on the subclass rather than generalizing them into the shared `IdentifiedJsonlLedger[T]` base (`src/jsonl_ledger.py`).

Example: `update_dispositions` wasn't pulled into the base after the migration because no sibling store (`EscapeLedger`, `InterventionLedger`, `TrendStore`) needs it.

**Why:** pulling one-off, store-specific behavior into a shared base reintroduces coupling the unification was meant to remove.
