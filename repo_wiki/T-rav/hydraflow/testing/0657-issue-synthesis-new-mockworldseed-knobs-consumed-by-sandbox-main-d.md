---
id: 0657
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.503293+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
---

# New MockWorldSeed knobs consumed by sandbox_main don't need apply_seed changes

When adding a `MockWorldSeed` field (e.g. `staging_enabled: bool`) that only needs to affect the sandbox HTTP harness, wire it in `src/mockworld/sandbox_main.py` via `object.__setattr__` after `_apply_sandbox_config_overrides` — leave the in-process `apply_seed` loader untouched if the relevant catalog builder (e.g. `_build_staging_promotion`) already forces the same value.

**Why:** Avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior the new knob controls.
