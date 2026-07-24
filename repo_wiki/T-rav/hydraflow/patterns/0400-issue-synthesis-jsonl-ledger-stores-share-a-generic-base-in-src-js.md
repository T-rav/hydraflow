---
id: 0400
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.612504+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
superseded_by: 0402
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

`EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` (in `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/audit/store.py`, `src/erosion/trends.py`) all subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` instead of each hand-rolling `path`/`read_all`/`append`.

Example: use `IdentifiedJsonlLedger[T]` when the row has an `id` (enables `existing_ids` dedup); use the plain base (as `TrendStore` does) when it doesn't.

**Why:** keeps read/write/dedup logic in one place so future stores don't reintroduce the same 40-line copy-paste the concept-scatter sensor flagged.
