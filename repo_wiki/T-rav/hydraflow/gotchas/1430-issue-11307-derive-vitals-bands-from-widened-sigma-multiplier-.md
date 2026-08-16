---
id: 1430
topic: gotchas
source_issue: 11307
source_phase: plan
created_at: 2026-08-16T05:25:13.887921+00:00
status: active
corroborations: 1
---

# Derive vitals bands from widened_sigma_multiplier, never hardcode

Derive vitals alarm bands dynamically using `vitals_methodology.widened_sigma_multiplier(n)`.
- In `src/objective_change_rate.py`, never hardcode 3.0 for sigma multipliers.
- Test band-edge noise and A→B→A reversals to ensure the dynamic band triggers correctly under ISA-18.2 hysteresis.
**Why:** Hardcoded thresholds break the hysteresis contract and fail to detect sustained hunting during fleet variance shifts.
