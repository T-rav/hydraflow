---
id: 0385
topic: patterns
source_issue: 10403
source_phase: plan
created_at: 2026-07-24T05:36:17.563750+00:00
status: superseded
corroborations: 1
superseded_by: 0388
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

`EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` (in `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/audit/store.py`, `src/erosion/trends.py`) all subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` instead of each hand-rolling `path`/`read_all`/`append`. Use `IdentifiedJsonlLedger[T]` when the row has an `id` (enables `existing_ids` dedup); use the plain base (as `TrendStore` does) when it doesn't.

**Why:** keeps read/write/dedup logic in one place so future stores don't reintroduce the same 40-line copy-paste the concept-scatter sensor flagged.
