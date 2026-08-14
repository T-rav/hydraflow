---
id: 2370
topic: testing
source_issue: 11084
source_phase: plan
created_at: 2026-08-14T05:53:19.138433+00:00
status: superseded
corroborations: 1
superseded_by: 2559
---

# Terminal verdicts must replay the recorded verdict, not INCONCLUSIVE

`EscapeAutoDiagnoser.diagnose` (`escape/auto_diagnose.py:333`) short-circuited already-terminal rows to `INCONCLUSIVE` despite its docstring promising the recorded verdict — a `DISMISSED` row then paged a human on the next tick.
- Return the recorded sidecar verdict; write nothing.
- `test_terminal_verdict_is_not_re_acted` (`tests/test_escape_auto_diagnose.py:251`) had pinned the drift (`second is INCONCLUSIVE`): correct the assertion, don't delete it.
**Why:** Re-acting a terminal verdict re-pages humans every tick; a test asserting the bug hides the contract violation.
