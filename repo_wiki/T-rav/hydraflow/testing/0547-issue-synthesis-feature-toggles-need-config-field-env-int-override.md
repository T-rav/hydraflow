---
id: 0547
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.122725+00:00
status: active
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
---

# Feature toggles need config field + _ENV_INT_OVERRIDES entry

Every config toggle requires both a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

Example: the `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
