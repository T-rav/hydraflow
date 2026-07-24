---
id: 0433
topic: gotchas
source_issue: 10318
source_phase: plan
created_at: 2026-07-24T04:19:41.513812+00:00
status: superseded
corroborations: 1
superseded_by: 0446
---

# Grep worker-name string repo-wide when retiring a loop, not just its .py file

A loop's short name (e.g. `pr_red_repair`) is duplicated as a string literal across UI/control surfaces beyond the loop class itself: `src/ui/src/constants.js`, `src/dashboard_routes/_control_routes.py`, `src/dashboard_routes/_common.py`, and sandbox seed scenarios (`tests/sandbox_scenarios/scenarios/s74_pr_red_repair_idle_poll.py`). Deleting only `src/pr_red_repair_loop.py` leaves dead controls or a scenario seeding a non-existent loop.

**Why:** these surfaces aren't caught by Python import errors or type checks — a missed one is a silent dead reference, not a build failure.
