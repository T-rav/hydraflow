---
id: 0069
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.339650+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# New automated skills must start with `blocking=False` until stable

Register new dynamic skills with `blocking=False` and graduate to `blocking=True` only after ≥20 runs at ≥95% success rate.

Example: a new lint-skill marked `blocking=True` on day one fails builds on edge cases the author didn't anticipate.

**Why:** Unproven blocking skills immediately break CI on legitimate code; graduated promotion ensures checks are stable before they can gate merges.
