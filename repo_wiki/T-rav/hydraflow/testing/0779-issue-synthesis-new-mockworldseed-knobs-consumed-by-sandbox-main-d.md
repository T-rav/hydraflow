---
id: 0779
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.337196+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# New MockWorldSeed knobs consumed by sandbox_main don't need apply_seed changes

When adding a `MockWorldSeed` field (e.g. `staging_enabled: bool`) that only needs to affect the sandbox HTTP harness, wire it in `src/mockworld/sandbox_main.py` via `object.__setattr__` after `_apply_sandbox_config_overrides`.

Example: leave the in-process `apply_seed` loader untouched if the relevant catalog builder (e.g. `_build_staging_promotion`) already forces the same value.

**Why:** avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior the new knob controls.
