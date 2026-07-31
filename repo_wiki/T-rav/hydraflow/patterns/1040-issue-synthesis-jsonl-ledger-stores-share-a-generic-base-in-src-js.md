---
id: 1040
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:49:30.462866+00:00
status: active
corroborations: 1
supersedes: 0973
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

Subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` for new append-only stores instead of hand-rolling `path`/`read_all`/`append`.

Example: `EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` all subclass one of these. Use `IdentifiedJsonlLedger[T]` when the row has an `id` (enables `existing_ids` dedup). See also: patterns — Ledger refactors must preserve byte-identical JSONL output.

**Why:** Keeps read/write/dedup logic in one place so future stores don't reintroduce the same copy-paste the concept-scatter sensor flagged.
