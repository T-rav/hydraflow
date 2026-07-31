---
id: 1747
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.026469+00:00
status: superseded
corroborations: 1
supersedes: 1653
superseded_by: 1852
---

# New MockWorldSeed knobs in sandbox_main skip apply_seed changes

When adding a MockWorldSeed field (e.g. staging_enabled: bool) that only needs to affect the sandbox HTTP harness, wire it in src/mockworld/sandbox_main.py via object.__setattr__ after _apply_sandbox_config_overrides.

Example: leave the in-process apply_seed loader untouched if the relevant catalog builder already forces the same value.

**Why:** Avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior.
