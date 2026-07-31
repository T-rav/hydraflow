---
id: 1238
topic: gotchas
source_issue: 10898
source_phase: plan
created_at: 2026-07-31T11:06:20.726209+00:00
status: active
corroborations: 1
---

# Dormant CI conclusions tracked as evidence, not as attempts

In `tally_job_stats` (`src/gate_health_loop.py:199`), record `skipped`/`cancelled`/`neutral`/empty conclusions as dormant evidence on `JobStats` without incrementing `attempts`.

- `attempts` stays terminal-only: passes + failures
- `runs_searched = attempts + skipped`
- Pass/fail rate denominators never include dormant records

**Why:** A "0% pass rate" finding on a gated check like `rc-promotion-scenario.yml` is only falsifiable if the reader can see how many runs were dormant vs. terminal.
