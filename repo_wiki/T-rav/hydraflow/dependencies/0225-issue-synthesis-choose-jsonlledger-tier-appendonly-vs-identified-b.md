---
id: 0225
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:27:56.451149+00:00
status: superseded
corroborations: 1
supersedes: 0210
superseded_by: 0241
---

# Choose JsonlLedger tier: AppendOnly vs Identified by dedup need

Pick the ledger tier by need: use `AppendOnlyJsonlLedger[S]` when dedup isn't needed, or `IdentifiedJsonlLedger[T]` when it is — both in `src/jsonl_ledger.py`.

Example: `TrendStore` (`src/erosion/trends.py`) subclasses the plain base; `AuditSampleLedger` (`src/audit/store.py`), `EscapeLedger` (`src/escape/ledger.py`), and `InterventionLedger` (`src/intervention/ledger.py`) subclass `IdentifiedJsonlLedger`.

**Why:** Prevents re-implementing append-only JSONL I/O per store while keeping dedup opt-in instead of forced on every ledger.
