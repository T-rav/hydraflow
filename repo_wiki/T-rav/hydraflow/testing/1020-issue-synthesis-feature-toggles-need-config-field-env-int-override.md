---
id: 1020
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.434227+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Feature toggles need config field + _ENV_INT_OVERRIDES tested both ways

Every config toggle requires both a field in src/config.py AND an entry in _ENV_INT_OVERRIDES. Test both the default value and the env-var override path.

Example: the _ENV_INT_OVERRIDES tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — _ENV_INT_OVERRIDES default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
