---
id: 0949
topic: testing
source_issue: 10498
source_phase: plan
created_at: 2026-07-25T01:51:29.166481+00:00
status: superseded
corroborations: 1
superseded_by: 0954
---

# tests/test_escape_ledger.py counter-pins must be rewritten, not deleted

When `src/escape/detect.py`'s `originating_pr` semantics change, the counter-pin assertions in `tests/test_escape_ledger.py` (e.g. `originating_pr == 777` near line 207, `== 4242` near line 196) must be rewritten to assert the new semantics, not simply removed.

**Why:** a deleted assertion still shows a green test run but proves nothing about the new behavior — this was flagged as a named pre-mortem risk in the #10498 plan, where deletion would silently pass while validating nothing.
