---
id: 0237
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T15:01:50.868261+00:00
status: active
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
---

# Feature toggles need both a config field and _ENV_INT_OVERRIDES entry

Every toggle requires both a field in `config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path. The `_ENV_INT_OVERRIDES` tuple default must equal the Field default or the override silently stops applying.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
