---
id: 0035
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.697259+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# New automated skills must start with `blocking=False` until proven stable

Register new dynamic skills with `blocking=False` and graduate to `blocking=True` only after ≥20 runs at ≥95% success rate.

Example: a new lint-skill marked `blocking=True` on day one fails builds on edge cases the author didn't anticipate.

**Why:** Unproven blocking skills immediately break CI on legitimate code; graduated promotion ensures checks are stable before they can gate merges.
