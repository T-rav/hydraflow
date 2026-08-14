---
id: 2559
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.450586+00:00
status: active
corroborations: 1
supersedes: 2370
---

# Terminal verdicts must replay the recorded verdict, not INCONCLUSIVE

`EscapeAutoDiagnoser.diagnose` (`escape/auto_diagnose.py:333`) must return the recorded sidecar verdict for already-terminal rows — not short-circuit to `INCONCLUSIVE`.

Example: `test_terminal_verdict_is_not_re_acted` (`tests/test_escape_auto_diagnose.py:251`) had pinned the drift (`second is INCONCLUSIVE`): correct the assertion, don't delete it.

**Why:** Re-acting a terminal verdict re-pages humans every tick; a test asserting the bug hides the contract violation.
