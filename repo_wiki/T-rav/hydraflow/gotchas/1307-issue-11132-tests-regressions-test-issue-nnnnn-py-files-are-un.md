---
id: 1307
topic: gotchas
source_issue: 11132
source_phase: plan
created_at: 2026-08-14T12:40:51.197500+00:00
status: active
corroborations: 1
---

# tests/regressions/test_issue_NNNNN.py files are uneditable acceptance pins

Regression test files named `tests/regressions/test_issue_11132.py` are RED pins created during issue triage. They define acceptance criteria and must pass **without edits**.

- Plan phases reference the current pass/fail count (e.g. "9 failed / 2 passed today") as a baseline.
- Implementation work makes all tests pass; no test in the file is modified.
- Unit coverage for the fix goes in the neighboring suite (e.g. `tests/test_prompt_telemetry.py`), not in the regression file.

**Why:** Editing the acceptance pin defeats its purpose as an independent verification of the fix and breaks traceability from issue to resolution.
