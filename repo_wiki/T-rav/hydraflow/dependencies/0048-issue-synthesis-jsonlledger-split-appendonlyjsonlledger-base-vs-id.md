---
id: 0048
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:48:28.316686+00:00
status: active
corroborations: 1
supersedes: 0042
---

# JsonlLedger split: AppendOnlyJsonlLedger base vs IdentifiedJsonlLedger

Pick the ledger tier by need instead of forcing dedup onto every ledger. `src/jsonl_ledger.py` splits into `AppendOnlyJsonlLedger[S]` (path/read_all/append only) and `IdentifiedJsonlLedger[T]` (adds `existing_ids` dedup on top).

Example: `TrendStore` (`src/erosion/trends.py`) has no dedup requirement so it subclasses the plain base; `AuditSampleLedger` (`src/audit/store.py`), `EscapeLedger` (`src/escape/ledger.py`), and `InterventionLedger` (`src/intervention/ledger.py`) all need id-based dedup so they subclass `IdentifiedJsonlLedger`.

**Why:** Prevents re-implementing append-only JSONL I/O per store while keeping dedup opt-in instead of forced on every ledger.
