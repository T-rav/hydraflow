---
id: 0432
topic: gotchas
source_issue: 10318
source_phase: plan
created_at: 2026-07-24T04:19:41.513801+00:00
status: active
corroborations: 1
---

# Consolidating a loop: retain its state counters/config caps, drop only cadence

When folding a standalone loop into another as an intake pass, keep the absorbed loop's persistence and gating config — only remove fields made redundant by the new driver's cadence. Example: `PrRedRepairLoop` → `PRUnstickerLoop` intake keeps `PRPort.rerun_workflow_failed`, `state/_pr_red_repair.py` ConvergenceLedger counters, and `pr_red_repair_*` enable-flags/caps in `src/config.py`, but drops `pr_red_repair_interval` since `PRUnstickerLoop` now owns cadence.

**Why:** dropping counters/caps alongside the loop wrapper silently loses coverage (bounded rerun limits, dedup state) that has nothing to do with which loop calls the code.
