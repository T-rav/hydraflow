---
id: 0475
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:40:09.614225+00:00
status: active
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

Subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` for new append-only stores instead of hand-rolling `path`/`read_all`/`append`.

Example: `EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` (in `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/audit/store.py`, `src/erosion/trends.py`) all subclass one of these; use `IdentifiedJsonlLedger[T]` when the row has an `id` (enables `existing_ids` dedup), the plain base otherwise. See also: patterns — Ledger refactors must preserve byte-identical JSONL output.

**Why:** keeps read/write/dedup logic in one place so future stores don't reintroduce the same 40-line copy-paste the concept-scatter sensor flagged.
