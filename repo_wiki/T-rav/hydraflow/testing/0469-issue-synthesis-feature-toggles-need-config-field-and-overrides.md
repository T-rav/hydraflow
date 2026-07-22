---
id: 0469
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.354135+00:00
status: active
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
---

# Feature toggles need config field and overrides

Every toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

Example: The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
