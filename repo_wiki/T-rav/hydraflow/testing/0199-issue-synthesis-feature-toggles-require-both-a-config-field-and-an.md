---
id: 0199
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.788379+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Feature toggles require both a config field and an _ENV_INT_OVERRIDES entry

Each new feature toggle needs a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default field value and the env-var override. The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or env override silently stops applying.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` default sync.

**Why:** A config field alone makes the toggle code-only; without `_ENV_INT_OVERRIDES`, the environment variable silently has no effect.
