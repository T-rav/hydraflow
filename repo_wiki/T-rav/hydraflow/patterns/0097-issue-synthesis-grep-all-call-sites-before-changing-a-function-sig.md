---
id: 0097
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:31:58.096882+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Grep all call sites before changing a function signature

Run `git grep <function_name>` before modifying any signature; for public functions, verify zero remaining unpatched matches after the change.

Example: `git grep 'load_state'` before changing its return type — update every caller in the same commit.

**Why:** Missing even one call site causes `TypeError` at runtime; exhaustive grep audit is the only way to confirm full coverage.
