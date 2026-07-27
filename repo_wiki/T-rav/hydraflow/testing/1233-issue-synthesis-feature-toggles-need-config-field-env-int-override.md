---
id: 1233
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:02.993058+00:00
status: superseded
corroborations: 1
supersedes: 1159
superseded_by: 1307
---

# Feature toggles need config field + _ENV_INT_OVERRIDES tested

Every config toggle requires both a field in src/config.py AND an entry in _ENV_INT_OVERRIDES. Test both the default value and the env-var override path.

Example: the _ENV_INT_OVERRIDES tuple default must equal the Field default or the override silently stops applying. See also: architecture — _ENV_INT_OVERRIDES default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
