---
id: 0142
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:41:45.185440+00:00
status: active
corroborations: 1
supersedes: 0131
---

# Choose JsonlLedger tier: AppendOnly vs Identified by dedup need

Pick the ledger tier by need: use `AppendOnlyJsonlLedger[S]` (path/read_all/append only) when dedup isn't needed, or `IdentifiedJsonlLedger[T]` (adds `existing_ids` dedup) when it is — both in `src/jsonl_ledger.py`.

Example: `TrendStore` (`src/erosion/trends.py`) subclasses the plain base; `AuditSampleLedger` (`src/audit/store.py`), `EscapeLedger` (`src/escape/ledger.py`), and `InterventionLedger` (`src/intervention/ledger.py`) subclass `IdentifiedJsonlLedger`.

**Why:** Prevents re-implementing append-only JSONL I/O per store while keeping dedup opt-in instead of forced on every ledger.
