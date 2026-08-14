---
id: 2419
topic: testing
source_issue: 11161
source_phase: plan
created_at: 2026-08-14T18:36:34.319408+00:00
status: active
corroborations: 1
---

# Inject fake diagnoser in loop tests that seed aged rows

Loop tests that seed aged findings hit the lazily-built production diagnoser when `escape_ledger_auto_diagnose_enabled` defaults `True`, shelling `git grep` against tmp repos.

- Inject a fake diagnoser via `tests/helpers.make_bg_loop_deps` or disable the config flag in those fixtures.
- Do not let tests accidentally exercise `auto_diagnose.regression_hits`' real `git grep`.

**Why:** Production diagnoser calls against tmp repos produce non-deterministic results and couple tests to repo state outside their control.
