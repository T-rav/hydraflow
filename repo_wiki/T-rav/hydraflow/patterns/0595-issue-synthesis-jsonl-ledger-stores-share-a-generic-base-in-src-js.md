---
id: 0595
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.339086+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# JSONL ledger stores share a generic base in src/jsonl_ledger.py

Subclass `AppendOnlyJsonlLedger[T]` or `IdentifiedJsonlLedger[T]` from `src/jsonl_ledger.py` for new append-only stores instead of hand-rolling `path`/`read_all`/`append`.

Example: `EscapeLedger`, `InterventionLedger`, `AuditSampleLedger`, and `TrendStore` all subclass one of these. See also: patterns — Ledger refactors must preserve byte-identical JSONL output.

**Why:** keeps read/write/dedup logic in one place so future stores don't reintroduce the same copy-paste the concept-scatter sensor flagged.
