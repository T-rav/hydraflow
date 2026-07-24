---
id: 0010
topic: dependencies
source_issue: 10449
source_phase: plan
created_at: 2026-07-24T12:33:05.988808+00:00
status: active
corroborations: 1
---

# JsonlLedger split: AppendOnlyJsonlLedger base + IdentifiedJsonlLedger for dedup

`src/jsonl_ledger.py` splits into a two-tier hierarchy: `AppendOnlyJsonlLedger[S]` (path/read_all/append only) and `IdentifiedJsonlLedger[T]` (adds `existing_ids` dedup on top). Pick the tier by need — `TrendStore` (`src/erosion/trends.py`) has no dedup requirement so it subclasses the plain base; `AuditSampleLedger` (`src/audit/store.py`), `EscapeLedger` (`src/escape/ledger.py`), and `InterventionLedger` (`src/intervention/ledger.py`) all need id-based dedup so they subclass `IdentifiedJsonlLedger`. **Why:** prevents re-implementing append-only JSONL I/O per store (the concept-scatter finding from #10403) while keeping dedup opt-in instead of forced on every ledger.
