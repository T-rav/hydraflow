---
id: 0623
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.464142+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Loop consolidation is a two-pass `_do_work`, not a merged single pass

When absorbing one loop's responsibility into another, drive the absorbed logic as a distinct second pass inside the host's `_do_work` rather than interleaving it into the first pass's control flow.

Example: `PRUnstickerLoop._do_work` runs the existing HITL unstick pass, then calls `PrRedIntake.run_once()` as a second, independently gated pass (skippable via `PRUnstickerLoop`'s kill-switch or `pr_red_repair_loop_enabled`).

**Why:** Keeping passes separate preserves independent enable-flag gating and avoids entangling two previously-independent failure/retry semantics into one code path.
