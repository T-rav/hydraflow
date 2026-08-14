---
id: 2562
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.536994+00:00
status: active
corroborations: 1
supersedes: 2373
---

# MockWorld scenarios test multi-tick accumulation in eval loops

Use `tests/scenarios/test_*_scenario.py` with `MockWorld` fakes to drive consecutive weekly ticks and verify accumulation behavior — e.g., a low-volume source files nothing until its window reaches the floor, then becomes judgeable; a degraded high-volume source still files on the first tick. This layer sits above unit tests and below sandbox e2e.

**Why:** Single-tick unit tests cannot catch carry-forward or re-anchoring bugs that only manifest across ticks.
