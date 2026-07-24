---
id: 0020
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:10:46.689055+00:00
status: active
corroborations: 1
supersedes: 0011,0012,0013,0014,0015
---

# JsonlLedger split: AppendOnlyJsonlLedger base + IdentifiedJsonlLedger for dedup

`src/jsonl_ledger.py` splits into a two-tier hierarchy: `AppendOnlyJsonlLedger[S]` (path/read_all/append only) and `IdentifiedJsonlLedger[T]` (adds `existing_ids` dedup on top). Pick the tier by need.

Example: `TrendStore` (`src/erosion/trends.py`) has no dedup requirement so it subclasses the plain base; `AuditSampleLedger` (`src/audit/store.py`), `EscapeLedger` (`src/escape/ledger.py`), and `InterventionLedger` (`src/intervention/ledger.py`) all need id-based dedup so they subclass `IdentifiedJsonlLedger`.

**Why:** prevents re-implementing append-only JSONL I/O per store while keeping dedup opt-in instead of forced on every ledger.
