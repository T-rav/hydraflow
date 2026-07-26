---
id: 1040
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.490237+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# New MockWorldSeed knobs consumed by sandbox_main skip apply_seed changes

When adding a MockWorldSeed field (e.g. staging_enabled: bool) that only needs to affect the sandbox HTTP harness, wire it in src/mockworld/sandbox_main.py via object.__setattr__ after _apply_sandbox_config_overrides.

Example: leave the in-process apply_seed loader untouched if the relevant catalog builder (e.g. _build_staging_promotion) already forces the same value.

**Why:** avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior the new knob controls.
