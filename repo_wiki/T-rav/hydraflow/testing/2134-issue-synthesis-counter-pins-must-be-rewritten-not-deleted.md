---
id: 2134
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.286124+00:00
status: superseded
corroborations: 1
supersedes: 2005
superseded_by: 2279
---

# Counter-pins must be rewritten, not deleted

When src/escape/detect.py's originating_pr semantics change, counter-pin assertions in tests/test_escape_ledger.py must be rewritten to assert the new semantics, not simply removed.

Example: assertions like `originating_pr == 777` near line 207 must be updated to assert the new value, not deleted.

**Why:** A deleted assertion still shows a green test run but proves nothing about the new behavior.
