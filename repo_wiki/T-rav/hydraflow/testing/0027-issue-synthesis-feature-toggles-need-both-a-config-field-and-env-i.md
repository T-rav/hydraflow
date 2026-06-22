---
id: 0027
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.410812+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Feature toggles need both a config field and _ENV_INT_OVERRIDES entry

Every toggle requires both a field in `config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default value and the env-var override path.

See also: memory `project_masked_timeout_rc_minus1.md` — tuple default must equal the Field default or the override silently stops applying.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
