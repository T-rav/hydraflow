---
id: 1168
topic: gotchas
source_issue: 10735
source_phase: plan
created_at: 2026-07-27T20:01:28.594785+00:00
status: active
corroborations: 1
---

# Self-solve ladder replaces HITL as route-back terminal

When a route-back exhausts its `GiveUpWindow`, the terminal path is `retry → decompose → diagnose → human-required`, not the old `diagnose → HITL`. `human-required` fires only when decompose declines AND diagnose is unavailable, and is logged at WARNING as a break — not a silent park.

- `src/self_solve_terminal.py` implements the ladder; `src/route_back.py` rewires from the old terminal
- Under the window, route-back relabels to `plan` and never calls self-solve

**Why:** Parking on a human (#10731) causes thrash; self-solve via children keeps issues converging.
