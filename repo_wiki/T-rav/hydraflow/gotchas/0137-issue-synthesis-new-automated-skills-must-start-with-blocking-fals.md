---
id: 0137
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.605452+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# New automated skills must start with blocking=False until stable

Register new dynamic skills with `blocking=False` and graduate to `blocking=True` only after ≥20 runs at ≥95% success rate.

Example: a new lint-skill marked `blocking=True` on day one fails builds on edge cases the author didn't anticipate.

**Why:** Unproven blocking skills immediately break CI on legitimate code; graduated promotion ensures checks are stable before they can gate merges.
