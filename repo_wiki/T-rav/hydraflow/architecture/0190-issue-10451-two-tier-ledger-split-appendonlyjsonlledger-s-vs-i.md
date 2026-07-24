---
id: 0190
topic: architecture
source_issue: 10451
source_phase: plan
created_at: 2026-07-24T12:15:48.605680+00:00
status: active
corroborations: 1
---

# Two-tier ledger split: AppendOnlyJsonlLedger[S] vs IdentifiedJsonlLedger[T]

Post-#10403, the single `JsonlLedger[T]` base class is gone. Ledgers now split into a plain tier (`AppendOnlyJsonlLedger[S]`: path/read_all/append, bound by `JsonlRow`) and a dedup tier (`IdentifiedJsonlLedger[T]`: extends AppendOnly, adds `existing_ids()`, bound by `Recordable`). `TrendStore` (`src/erosion/trends.py`) sits in the plain tier since its `ChangeDatapoint` records have no stable id; `AuditSampleLedger`/`EscapeLedger`/`InterventionLedger` sit in the identified tier. When adding a new jsonl-backed store, pick the tier based on whether records need id-based dedup, not by copying an existing ledger.
**Why:** conflating the tiers (e.g. giving TrendStore `existing_ids()`) reintroduces the pre-#10403 design flaw the split was meant to fix.
