---
id: 0475
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.398387+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Grep worker-name string repo-wide when retiring a loop, not just its .py file

A loop's short name (e.g. `pr_red_repair`) is duplicated as a string literal across UI/control surfaces beyond the loop class itself: `src/ui/src/constants.js`, `src/dashboard_routes/_control_routes.py`, `src/dashboard_routes/_common.py`, and sandbox seed scenarios (`tests/sandbox_scenarios/scenarios/s74_pr_red_repair_idle_poll.py`). Deleting only `src/pr_red_repair_loop.py` leaves dead controls or a scenario seeding a non-existent loop.

**Why:** these surfaces aren't caught by Python import errors or type checks — a missed one is a silent dead reference, not a build failure.
