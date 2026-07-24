---
id: 0573
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.215119+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Consolidating a loop: retain its state counters/config caps, drop only cadence

When folding a standalone loop into another as an intake pass, keep the absorbed loop's persistence and gating config — only remove fields made redundant by the new driver's cadence.

Example: `PrRedRepairLoop` → `PRUnstickerLoop` intake keeps `PRPort.rerun_workflow_failed`, `state/_pr_red_repair.py` ConvergenceLedger counters, and `pr_red_repair_*` enable-flags/caps in `src/config.py`, but drops `pr_red_repair_interval` since `PRUnstickerLoop` now owns cadence.

**Why:** Dropping counters/caps alongside the loop wrapper silently loses coverage (bounded rerun limits, dedup state) that has nothing to do with which loop calls the code.
