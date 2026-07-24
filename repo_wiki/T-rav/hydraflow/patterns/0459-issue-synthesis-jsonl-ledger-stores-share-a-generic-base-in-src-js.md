---
id: 0459
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:37:14.521983+00:00
status: superseded
corroborations: 1
supersedes: 0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0463
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

Subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` for new append-only stores instead of hand-rolling `path`/`read_all`/`append`.

Example: `EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` (in `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/audit/store.py`, `src/erosion/trends.py`) all subclass one of these; use `IdentifiedJsonlLedger[T]` when the row has an `id` (enables `existing_ids` dedup), the plain base otherwise. See also: patterns — Ledger refactors must preserve byte-identical JSONL output.

**Why:** keeps read/write/dedup logic in one place so future stores don't reintroduce the same 40-line copy-paste the concept-scatter sensor flagged.
