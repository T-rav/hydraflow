---
id: 0425
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.297285+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Open-PR failure modes map to one owning shepherd loop each

Every stuck-open-PR state has exactly one owning loop, not a shared monitor. FAILURE (red CI) → `PRRedRepairLoop` (rerun + real-red dispatch); DIRTY (merge conflict) → `MergeStateWatcher` + arch-regen self-heal; green-but-unmerged → `DependabotMergeLoop` class-5 path. Before adding a new watcher for an open-PR condition, check which of these three already owns it — see `docs/wiki/patterns.md` entry "Open-PR failure modes each have an owning shepherd loop".

**Why:** prevents duplicate loops competing to fix the same PR state (scope-creep trap called out for issue #10293).
