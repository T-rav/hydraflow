---
id: 1203
topic: gotchas
source_issue: 10799
source_phase: plan
created_at: 2026-07-28T10:31:44.654954+00:00
status: active
corroborations: 1
---

# Boot issue:null container must be closable and issue-scoped

Rule: The boot `Idle` event publishes with no issue (`src/server.py:403`, `{"phase":"idle"}`). Its container must carry `issue: null`, hold only issue-less events, and gain a non-null `endTs` at the first per-issue container start. **Why:** Leaving it open forever swallows per-issue PR rows; guards 3 and 4 in `tests/regressions/test_issue_10799.py` pin both failure modes — the container must be issue-less AND closable.
