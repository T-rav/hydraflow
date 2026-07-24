---
id: 0671
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.465632+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# Consolidating a loop: retain its state counters/config caps, drop only cadence

When folding a standalone loop into another as an intake pass, keep the absorbed loop's persistence and gating config — only remove fields made redundant by the new driver's cadence.

Example: `PrRedRepairLoop` → `PRUnstickerLoop` intake keeps `PRPort.rerun_workflow_failed`, `state/_pr_red_repair.py` ConvergenceLedger counters, and `pr_red_repair_*` enable-flags/caps in `src/config.py`, but drops `pr_red_repair_interval` since `PRUnstickerLoop` now owns cadence.

**Why:** Dropping counters/caps alongside the loop wrapper silently loses coverage (bounded rerun limits, dedup state) that has nothing to do with which loop calls the code.
