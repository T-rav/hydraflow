---
id: 0794
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:03.993201+00:00
status: superseded
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
superseded_by: 0851
---

# Loop consolidation is a two-pass `_do_work`, not a merged single pass

When absorbing one loop's responsibility into another, drive the absorbed logic as a distinct second pass inside the host's `_do_work` rather than interleaving it into the first pass's control flow.

Example: `PRUnstickerLoop._do_work` runs the existing HITL unstick pass, then calls `PrRedIntake.run_once()` as a second, independently gated pass (skippable via `PRUnstickerLoop`'s kill-switch or `pr_red_repair_loop_enabled`).

**Why:** Keeping passes separate preserves independent enable-flag gating and avoids entangling two previously-independent failure/retry semantics into one code path.
