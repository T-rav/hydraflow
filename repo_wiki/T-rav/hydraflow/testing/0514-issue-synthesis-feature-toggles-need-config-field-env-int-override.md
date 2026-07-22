---
id: 0514
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:10:40.686027+00:00
status: active
corroborations: 1
supersedes: 0500,0501,0502,0503,0504,0505,0506,0507,0508,0509
---

# Feature toggles need config field + _ENV_INT_OVERRIDES entry

Every config toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

Example: The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
