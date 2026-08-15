---
id: 2639
topic: testing
source_issue: 11227
source_phase: plan
created_at: 2026-08-15T06:51:55.204483+00:00
status: active
corroborations: 1
---

# MockWorldSeed new fields must be optional with zero existing-scenario impact

Any new field on `MockWorldSeed` (e.g. `branches`) must be optional with a sensible default. Both seed loaders (`apply_seed` in `tests/scenarios/fakes/mock_world.py` and the direct constructor) must handle its absence identically.

**Why:** Existing scenarios construct `MockWorldSeed` without the new field; a required field or asymmetric default silently breaks scenario setup across the test suite.
