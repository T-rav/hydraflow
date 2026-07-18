---
id: 0273
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:12:03.100749+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Feature toggles need both a config field and _ENV_INT_OVERRIDES entry

Every toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
