---
id: 0136
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.435662+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Feature toggles require both a config field and an _ENV_INT_OVERRIDES entry

Each new feature toggle needs a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default field value and the env-var override behavior. The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or env override silently stops applying.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` default sync.

**Why:** A config field alone makes the toggle code-only; without `_ENV_INT_OVERRIDES`, the environment variable silently has no effect.
