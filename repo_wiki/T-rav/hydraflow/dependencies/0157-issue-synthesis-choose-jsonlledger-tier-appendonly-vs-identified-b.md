---
id: 0157
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:26:28.551946+00:00
status: superseded
corroborations: 1
supersedes: 0142
superseded_by: 0168
---

# Choose JsonlLedger tier: AppendOnly vs Identified by dedup need

Pick the ledger tier by need: use `AppendOnlyJsonlLedger[S]` (path/read_all/append only) when dedup isn't needed, or `IdentifiedJsonlLedger[T]` (adds `existing_ids` dedup) when it is — both in `src/jsonl_ledger.py`.

Example: `TrendStore` (`src/erosion/trends.py`) subclasses the plain base; `AuditSampleLedger` (`src/audit/store.py`), `EscapeLedger` (`src/escape/ledger.py`), and `InterventionLedger` (`src/intervention/ledger.py`) subclass `IdentifiedJsonlLedger`.

**Why:** Prevents re-implementing append-only JSONL I/O per store while keeping dedup opt-in instead of forced on every ledger.
