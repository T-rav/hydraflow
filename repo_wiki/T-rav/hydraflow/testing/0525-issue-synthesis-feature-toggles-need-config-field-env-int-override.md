---
id: 0525
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:39:13.367018+00:00
status: active
corroborations: 1
supersedes: 0510,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519
---

# Feature toggles need config field + _ENV_INT_OVERRIDES entry

Every config toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

Example: the `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
