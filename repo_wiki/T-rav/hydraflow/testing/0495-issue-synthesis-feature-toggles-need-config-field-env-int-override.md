---
id: 0495
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:16:53.881470+00:00
status: superseded
corroborations: 1
supersedes: 0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491
superseded_by: 0500
---

# Feature toggles need config field + _ENV_INT_OVERRIDES entry

Every config toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

Example: The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
