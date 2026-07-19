---
id: 0205
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.159052+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# New automated skills must start with blocking=False until stable

Register new dynamic skills with `blocking=False` and graduate to `blocking=True` only after ≥20 runs at ≥95% success rate.

Example: a new lint-skill marked `blocking=True` on day one fails builds on edge cases the author didn't anticipate.

**Why:** Unproven blocking skills immediately break CI on legitimate code; graduated promotion ensures checks are stable before they can gate merges.
