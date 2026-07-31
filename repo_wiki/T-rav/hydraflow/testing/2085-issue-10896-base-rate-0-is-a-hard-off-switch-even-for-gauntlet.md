---
id: 2085
topic: testing
source_issue: 10896
source_phase: plan
created_at: 2026-07-31T12:32:01.782707+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# base_rate==0 is a hard off-switch even for gauntlet stratum

The `prob <= 0.0: continue` guard in `select_sample` survives the gauntlet bypass. An explicit `base_rate == 0` disables all sampling including gauntlet.

- The loop floors to `DEFAULT_BASE_RATE` when unset, but explicit `0` means no sampling at all
- No stratum gets special treatment over the off-switch

**Why:** Preserves a single kill-switch for the entire audit loop without per-stratum carve-outs that could accidentally re-enable sampling.
