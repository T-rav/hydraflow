---
id: 0895
topic: patterns
source_issue: 10820
source_phase: plan
created_at: 2026-07-31T00:58:39.724668+00:00
status: active
corroborations: 1
---

# Label spend-cap gaps in time series instead of dropping them

The 8-week analysis window straddles 07-02/03 spend caps. Those data gaps are cap artifacts, not quiet periods. Series 5 labels them explicitly rather than treating them as zero-flux weeks.

**Why:** Dropping or zero-filling cap-artifact gaps would understate flux and distort the flux-share ranking toward loops active during non-capped weeks.
