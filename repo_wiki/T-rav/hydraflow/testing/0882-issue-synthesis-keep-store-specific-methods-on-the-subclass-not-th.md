---
id: 0882
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.543000+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0898
---

# Keep store-specific methods on the subclass, not the shared ledger base

Keep store-specific methods like `AuditSampleLedger.update_dispositions` (`src/audit/store.py`) defined on the subclass rather than generalizing them into the shared `IdentifiedJsonlLedger[T]` base (`src/jsonl_ledger.py`).

Example: `update_dispositions` wasn't pulled into the base after the migration because no sibling store (`EscapeLedger`, `InterventionLedger`, `TrendStore`) needs it.

**Why:** pulling one-off, store-specific behavior into a shared base reintroduces coupling the unification was meant to remove.
