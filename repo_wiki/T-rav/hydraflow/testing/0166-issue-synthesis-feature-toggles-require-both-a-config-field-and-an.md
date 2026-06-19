---
id: 0166
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.578470+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Feature toggles require both a config field and an _ENV_INT_OVERRIDES entry

Each new feature toggle needs a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default field value and the env-var override behavior. The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or env override silently stops applying.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` default sync.

**Why:** A config field alone makes the toggle code-only; without `_ENV_INT_OVERRIDES`, the environment variable silently has no effect.
