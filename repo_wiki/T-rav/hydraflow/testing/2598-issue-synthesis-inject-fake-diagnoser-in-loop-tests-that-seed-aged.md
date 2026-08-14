---
id: 2598
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:52.084484+00:00
status: active
corroborations: 1
supersedes: 2419
---

# Inject fake diagnoser in loop tests that seed aged rows

Loop tests that seed aged findings hit the lazily-built production diagnoser when `escape_ledger_auto_diagnose_enabled` defaults `True`, shelling `git grep` against tmp repos.

Example: inject a fake diagnoser via `tests/helpers.make_bg_loop_deps` or disable the config flag in those fixtures. Do not let tests accidentally exercise `auto_diagnose.regression_hits`' real `git grep`.

**Why:** Production diagnoser calls against tmp repos produce non-deterministic results and couple tests to repo state outside their control.
