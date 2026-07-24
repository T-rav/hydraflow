---
id: 0697
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.870333+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# New MockWorldSeed knobs consumed by sandbox_main don't need apply_seed changes

When adding a `MockWorldSeed` field (e.g. `staging_enabled: bool`) that only needs to affect the sandbox HTTP harness, wire it in `src/mockworld/sandbox_main.py` via `object.__setattr__` after `_apply_sandbox_config_overrides`.

Example: leave the in-process `apply_seed` loader untouched if the relevant catalog builder (e.g. `_build_staging_promotion`) already forces the same value.

**Why:** avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior the new knob controls.
