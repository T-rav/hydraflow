---
id: 0434
topic: gotchas
source_issue: 10318
source_phase: plan
created_at: 2026-07-24T04:19:41.513829+00:00
status: active
corroborations: 1
---

# Loop consolidation is a two-pass `_do_work`, not a merged single pass

When absorbing one loop's responsibility into another, drive the absorbed logic as a distinct second pass inside the host's `_do_work` rather than interleaving it into the first pass's control flow. `PRUnstickerLoop._do_work` runs the existing HITL unstick pass, then calls `PrRedIntake.run_once()` as a second, independently gated pass (skippable via `PRUnstickerLoop`'s kill-switch or `pr_red_repair_loop_enabled`).

**Why:** keeping passes separate preserves independent enable-flag gating and avoids entangling two previously-independent failure/retry semantics into one code path.
