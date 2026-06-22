---
id: 0047
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.212679+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Feature toggles require both a config field and an _ENV_INT_OVERRIDES entry

Each new feature toggle needs a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default field value and the env-var override behavior.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` tuple default must equal the Field default or env override silently stops applying.

**Why:** A config field alone makes the toggle code-only; without `_ENV_INT_OVERRIDES`, the environment variable silently has no effect.
