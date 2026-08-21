---
id: 0296
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-21T11:38:32.594688+00:00
status: active
corroborations: 1
supersedes: 0277
---

# Choose JsonlLedger tier: AppendOnly vs Identified by dedup need

Pick the ledger tier by need: use `AppendOnlyJsonlLedger[S]` when dedup isn't needed, or `IdentifiedJsonlLedger[T]` when it is — both in `src/jsonl_ledger.py`.

Example: `TrendStore` (`src/erosion/trends.py`) subclasses the plain base; `AuditSampleLedger`, `EscapeLedger`, and `InterventionLedger` subclass `IdentifiedJsonlLedger`.

**Why:** Prevents re-implementing append-only JSONL I/O per store while keeping dedup opt-in instead of forced on every ledger.
