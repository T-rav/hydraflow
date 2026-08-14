---
id: 2555
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.389081+00:00
status: active
corroborations: 1
supersedes: 2366
---

# Guard-test ADR population filters against adr_conformance.py

Pin the Accepted-only ADR population filter to its source at `src/adr_conformance.py:498` via a guard test; never introduce a second Accepted-status filter.

Example: `tests/test_setpoint_population.py` asserts that non-Accepted statuses are excluded both in `setpoint/population.py` and by `evaluate_adrs`.

**Why:** Duplicate population filters drift independently; a single pinned source of truth prevents population-definition skew across modules.
