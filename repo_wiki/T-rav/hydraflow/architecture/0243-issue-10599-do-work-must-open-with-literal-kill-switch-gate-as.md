---
id: 0243
topic: architecture
source_issue: 10599
source_phase: plan
created_at: 2026-07-26T11:44:58.431667+00:00
status: active
corroborations: 1
---

# _do_work must open with literal kill-switch gate (AST-matched)

`_do_work` must begin with `if not self._enabled_cb(self._worker_name): return {"status": "disabled"}` — verbatim.

- `test_loop_kill_switch_completeness.py` AST-matches this exact statement.
- A different guard form or renamed callback breaks the test at import time.

**Why:** The kill-switch completeness test is structural, not behavioral — it pattern-matches source text, so deviations silently bypass the safety check.
