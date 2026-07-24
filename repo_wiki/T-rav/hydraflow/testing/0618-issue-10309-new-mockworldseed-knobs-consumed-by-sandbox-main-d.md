---
id: 0618
topic: testing
source_issue: 10309
source_phase: plan
created_at: 2026-07-24T04:15:22.309943+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# New MockWorldSeed knobs consumed by sandbox_main don't need apply_seed changes

When adding a `MockWorldSeed` field (e.g. `staging_enabled: bool`) that only needs to affect the sandbox HTTP harness, wire it in `src/mockworld/sandbox_main.py` via `object.__setattr__` after `_apply_sandbox_config_overrides` — leave the in-process `apply_seed` loader untouched if the relevant catalog builder (e.g. `_build_staging_promotion`) already forces the same value.
**Why:** Avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior the new knob controls.
