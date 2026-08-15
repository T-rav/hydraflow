---
id: 2625
topic: testing
source_issue: 11192
source_phase: plan
created_at: 2026-08-15T00:51:35.394371+00:00
status: active
corroborations: 1
---

# Counter-pin guards protect assertion strength in self-retiring tests

When making a regression test self-retiring (e.g. `test_issue_9565.py`), add a RED guard test (e.g. `test_issue_11192.py`) with a counter-pin that flags both hard-coded filename pins and bare `next(...)` index lookups — while not flagging the correct `ADRIndex` + `None` default + `is_live` pattern.

**Why:** Without the counter-pin, a future change could weaken the original assertion under the guise of retirement, silently dropping the #9565 coverage.
