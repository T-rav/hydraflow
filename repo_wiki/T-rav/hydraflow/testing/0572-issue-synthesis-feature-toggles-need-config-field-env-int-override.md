---
id: 0572
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.420867+00:00
status: superseded
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
superseded_by: 0593
---

# Feature toggles need config field + _ENV_INT_OVERRIDES entry

Every config toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

Example: the `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
