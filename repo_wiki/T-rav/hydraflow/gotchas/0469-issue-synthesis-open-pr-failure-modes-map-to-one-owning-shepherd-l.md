---
id: 0469
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.394348+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
---

# Open-PR failure modes map to one owning shepherd loop each

Every stuck-open-PR state has exactly one owning loop, not a shared monitor. FAILURE (red CI) → `PRRedRepairLoop` (rerun + real-red dispatch); DIRTY (merge conflict) → `MergeStateWatcher` + arch-regen self-heal; green-but-unmerged → `DependabotMergeLoop` class-5 path. Before adding a new watcher for an open-PR condition, check which of these three already owns it — see `docs/wiki/patterns.md` entry "Open-PR failure modes each have an owning shepherd loop".

**Why:** prevents duplicate loops competing to fix the same PR state (scope-creep trap called out for issue #10293).
