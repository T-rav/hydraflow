---
id: 2674
topic: testing
source_issue: 11235
source_phase: plan
created_at: 2026-08-16T05:30:59.489423+00:00
status: active
corroborations: 1
---

# Regression pins assert observed spawn, not helper invocations

Tests in `tests/regressions/` assert `StreamConfig.provider` and `--model` in the spawned `cmd`, not that a specific helper was called. When writing regression pins for provider routing, assert the observed spawn configuration.

**Why:** Pins survive refactors of internal call structure while still catching the actual failure mode — wrong provider at spawn time.
