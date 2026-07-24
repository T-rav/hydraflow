---
id: 0672
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.466690+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# Grep worker-name string repo-wide when retiring a loop, not just its .py file

A loop's short name (e.g. `pr_red_repair`) is duplicated as a string literal across UI/control surfaces beyond the loop class itself.

Example: `src/ui/src/constants.js`, `src/dashboard_routes/_control_routes.py`, `src/dashboard_routes/_common.py`, and sandbox seed scenarios (`tests/sandbox_scenarios/scenarios/s74_pr_red_repair_idle_poll.py`) all reference it; deleting only `src/pr_red_repair_loop.py` leaves dead controls or a scenario seeding a non-existent loop.

**Why:** These surfaces aren't caught by Python import errors or type checks — a missed one is a silent dead reference, not a build failure.
