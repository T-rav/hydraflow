---
id: 0474
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.397711+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# Consolidating a loop: retain its state counters/config caps, drop only cadence

When folding a standalone loop into another as an intake pass, keep the absorbed loop's persistence and gating config — only remove fields made redundant by the new driver's cadence. Example: `PrRedRepairLoop` → `PRUnstickerLoop` intake keeps `PRPort.rerun_workflow_failed`, `state/_pr_red_repair.py` ConvergenceLedger counters, and `pr_red_repair_*` enable-flags/caps in `src/config.py`, but drops `pr_red_repair_interval` since `PRUnstickerLoop` now owns cadence.

**Why:** dropping counters/caps alongside the loop wrapper silently loses coverage (bounded rerun limits, dedup state) that has nothing to do with which loop calls the code.
