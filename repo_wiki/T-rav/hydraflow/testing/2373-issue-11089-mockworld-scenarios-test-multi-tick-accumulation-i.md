---
id: 2373
topic: testing
source_issue: 11089
source_phase: plan
created_at: 2026-08-14T06:37:49.577210+00:00
status: superseded
corroborations: 1
superseded_by: 2562
---

# MockWorld scenarios test multi-tick accumulation in eval loops

Use `tests/scenarios/test_*_scenario.py` with `MockWorld` fakes to drive consecutive weekly ticks and verify accumulation behavior — e.g., a low-volume source files nothing until its window reaches the floor, then becomes judgeable; a degraded high-volume source still files on the first tick. This layer sits above unit tests and below sandbox e2e.

**Why:** Single-tick unit tests cannot catch carry-forward or re-anchoring bugs that only manifest across ticks.
