---
id: 2367
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.149321+00:00
status: superseded
corroborations: 1
supersedes: 2226
superseded_by: 2556
---

# Arch generator tests: byte-for-byte determinism, no MockWorld

Test arch generators by rendering the same synthetic corpus twice and asserting byte-for-byte equality; no MockWorld or sandbox tier.

Example: follow `tests/test_gauntlet_calibration_generator.py` as the template for `tests/test_arch_setpoint_erosion.py`. The gate is `tests/architecture/` + `make arch-regen` staleness + `make quality`.

**Why:** Non-deterministic generators produce `make arch-regen` staleness noise; byte-for-byte equality is the required gate.
