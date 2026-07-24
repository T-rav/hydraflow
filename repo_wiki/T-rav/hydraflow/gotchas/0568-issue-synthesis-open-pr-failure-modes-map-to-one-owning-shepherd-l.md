---
id: 0568
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.195483+00:00
status: superseded
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
superseded_by: 0593
---

# Open-PR failure modes map to one owning shepherd loop each

Every stuck-open-PR state has exactly one owning loop, not a shared monitor.

Example: FAILURE (red CI) → `PRRedRepairLoop` (rerun + real-red dispatch); DIRTY (merge conflict) → `MergeStateWatcher` + arch-regen self-heal; green-but-unmerged → `DependabotMergeLoop` class-5 path. Before adding a new watcher for an open-PR condition, check which of these three already owns it — see `docs/wiki/patterns.md` entry "Open-PR failure modes each have an owning shepherd loop".

**Why:** Prevents duplicate loops competing to fix the same PR state (scope-creep trap called out for issue #10293).
