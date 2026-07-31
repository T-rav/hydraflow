---
id: 2225
topic: testing
source_issue: 10918
source_phase: plan
created_at: 2026-07-31T15:55:12.930268+00:00
status: active
corroborations: 1
---

# Guard-test ADR population filters against adr_conformance.py

Pin the Accepted-only ADR population filter to its source at `src/adr_conformance.py:498` via a guard test; never introduce a second Accepted-status filter.

`tests/test_setpoint_population.py` asserts that non-Accepted statuses are excluded both in `setpoint/population.py` and by `evaluate_adrs`.

**Why:** Duplicate population filters drift independently; a single pinned source of truth prevents population-definition skew across modules.
