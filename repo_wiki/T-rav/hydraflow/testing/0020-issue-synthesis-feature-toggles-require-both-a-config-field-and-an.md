---
id: 0020
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.829459+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Feature toggles require both a config field and an _ENV_INT_OVERRIDES entry

Each new feature toggle needs a field in `src/config.py` AND an entry in `_ENV_INT_OVERRIDES`. Test both the default field value and the env-var override behavior.

See also: architecture-state-persistence — `_ENV_INT_OVERRIDES` tuple default must equal the Field default or env override silently stops applying.

**Why:** A config field alone makes the toggle code-only; without the `_ENV_INT_OVERRIDES` entry, the environment variable silently has no effect.
