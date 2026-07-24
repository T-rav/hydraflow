---
id: 0616
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.247213+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Open-PR failure modes map to one owning shepherd loop each

Every stuck-open-PR state has exactly one owning loop, not a shared monitor.

Example: FAILURE (red CI) → `PRRedRepairLoop` (rerun + real-red dispatch); DIRTY (merge conflict) → `MergeStateWatcher` + arch-regen self-heal; green-but-unmerged → `DependabotMergeLoop` class-5 path. Before adding a new watcher for an open-PR condition, check which of these three already owns it — see `docs/wiki/patterns.md` entry "Open-PR failure modes each have an owning shepherd loop".

**Why:** Prevents duplicate loops competing to fix the same PR state (scope-creep trap called out for issue #10293).
