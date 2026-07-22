---
id: 0273
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.031581+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# New automated skills must start with blocking=False until stable

Register new dynamic skills with `blocking=False` and graduate to `blocking=True` only after ≥20 runs at ≥95% success rate.

Example: a new lint-skill marked `blocking=True` on day one fails builds on edge cases the author didn't anticipate.

**Why:** Unproven blocking skills immediately break CI on legitimate code; graduated promotion ensures checks are stable before they can gate merges.
