---
id: 2556
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.394369+00:00
status: active
corroborations: 1
supersedes: 2367
---

# Arch generator tests: byte-for-byte determinism, no MockWorld

Test arch generators by rendering the same synthetic corpus twice and asserting byte-for-byte equality; no MockWorld or sandbox tier.

Example: follow `tests/test_gauntlet_calibration_generator.py` as the template for `tests/test_arch_setpoint_erosion.py`. The gate is `tests/architecture/` + `make arch-regen` staleness + `make quality`.

**Why:** Non-deterministic generators produce `make arch-regen` staleness noise; byte-for-byte equality is the required gate.
