---
id: 0524
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.793118+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Loop consolidation is a two-pass `_do_work`, not a merged single pass

When absorbing one loop's responsibility into another, drive the absorbed logic as a distinct second pass inside the host's `_do_work` rather than interleaving it into the first pass's control flow.

Example: `PRUnstickerLoop._do_work` runs the existing HITL unstick pass, then calls `PrRedIntake.run_once()` as a second, independently gated pass (skippable via `PRUnstickerLoop`'s kill-switch or `pr_red_repair_loop_enabled`).

**Why:** Keeping passes separate preserves independent enable-flag gating and avoids entangling two previously-independent failure/retry semantics into one code path.
