---
id: 0013
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.313872+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Grep all call sites before changing a function signature

Run `git grep <function_name>` before modifying any signature; for public functions, verify zero remaining unpatched matches after the change.

Example: `git grep 'load_state'` before changing its return type — update every caller in the same commit.

**Why:** Missing even one call site causes `TypeError` at runtime; exhaustive grep audit is the only way to confirm full coverage.
