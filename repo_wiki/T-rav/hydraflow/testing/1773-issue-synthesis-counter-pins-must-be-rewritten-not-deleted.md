---
id: 1773
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.079940+00:00
status: active
corroborations: 1
supersedes: 1679
---

# Counter-pins must be rewritten, not deleted

When src/escape/detect.py's originating_pr semantics change, counter-pin assertions in tests/test_escape_ledger.py must be rewritten to assert the new semantics, not simply removed.

Example: assertions like `originating_pr == 777` near line 207 must be updated to assert the new value, not deleted.

**Why:** A deleted assertion still shows a green test run but proves nothing about the new behavior.
