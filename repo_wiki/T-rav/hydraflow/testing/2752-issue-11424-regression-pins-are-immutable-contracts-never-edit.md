---
id: 2752
topic: testing
source_issue: 11424
source_phase: plan
created_at: 2026-08-18T04:14:44.048799+00:00
status: active
corroborations: 1
---

# Regression pins are immutable contracts — never edit to make green

Files like `tests/regressions/test_issue_11424.py` are pre-written RED pins with specific port keys (`auto_diagnoser`, `refine_llm`, `workspace`) and private attrs (`_auto_diagnoser`, `_refine_llm`, `_workspaces`). The fix is correct only if the pin flips GREEN unmodified.

If you need to edit the pin to pass, the fix is wrong — re-examine the builder wiring, not the test.

**Why:** Editing the pin to match the implementation defeats its purpose as a recurrence guard and hides future regressions.
