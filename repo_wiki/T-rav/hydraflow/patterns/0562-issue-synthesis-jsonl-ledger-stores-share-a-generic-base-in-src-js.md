---
id: 0562
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.749769+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0584
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

Subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` for new append-only stores instead of hand-rolling `path`/`read_all`/`append`.

Example: `EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` (in `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/audit/store.py`, `src/erosion/trends.py`) all subclass one of these; use `IdentifiedJsonlLedger[T]` when the row has an `id` (enables `existing_ids` dedup), the plain base otherwise. See also: patterns — Ledger refactors must preserve byte-identical JSONL output.

**Why:** keeps read/write/dedup logic in one place so future stores don't reintroduce the same 40-line copy-paste the concept-scatter sensor flagged.
