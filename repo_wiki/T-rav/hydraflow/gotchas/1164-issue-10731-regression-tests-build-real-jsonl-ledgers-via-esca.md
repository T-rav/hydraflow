---
id: 1164
topic: gotchas
source_issue: 10731
source_phase: plan
created_at: 2026-07-27T18:39:53.932383+00:00
status: active
corroborations: 1
---

# Regression tests build real JSONL ledgers via EscapeLedger.append, no stubs

Regression tests under `tests/regressions/test_issue_NNNNN.py` construct ledger state through `EscapeLedger.append` / `append_resolution` rather than hand-crafted row dicts.

Example: `test_issue_10731.py` appends a low-confidence surface and a sibling regression-pin, then asserts reconciliation closes the issue.

**Why:** Stubbed rows skip the collapse logic in `read_latest()`, hiding the exact class of fold-away bug being tested.
