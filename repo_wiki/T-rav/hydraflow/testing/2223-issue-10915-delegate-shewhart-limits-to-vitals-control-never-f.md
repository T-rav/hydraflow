---
id: 2223
topic: testing
source_issue: 10915
source_phase: plan
created_at: 2026-07-31T15:36:39.647846+00:00
status: superseded
corroborations: 1
superseded_by: 2230
---

# Delegate Shewhart limits to vitals.control, never fork

Do not re-implement sigma/moving-range arithmetic under `src/setpoint/`. Call `vitals.control.individuals_limits` directly and add an equality test asserting the returned limits match `vitals.control` for the same baseline.

**Why:** Forked control-limit math drifts silently from the fleet standard, producing inconsistent breach detection across instruments — the same failure mode that copying `vitals/control.py` would introduce.
