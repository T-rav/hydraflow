---
id: 0055
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:09:01.905662+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Grep all call sites before changing a function signature

Run `git grep <function_name>` before modifying any signature; for public functions, verify zero remaining unpatched matches after the change.

Example: `git grep 'load_state'` before changing its return type — update every caller in the same commit.

**Why:** Missing even one call site causes `TypeError` at runtime; exhaustive grep audit is the only way to confirm full coverage.
