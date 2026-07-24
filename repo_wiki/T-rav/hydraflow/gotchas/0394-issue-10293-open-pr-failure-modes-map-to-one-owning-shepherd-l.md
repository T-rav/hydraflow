---
id: 0394
topic: gotchas
source_issue: 10293
source_phase: plan
created_at: 2026-07-22T18:20:50.899406+00:00
status: active
corroborations: 1
---

# Open-PR failure modes map to one owning shepherd loop each

Every stuck-open-PR state has exactly one owning loop, not a shared monitor. FAILURE (red CI) → `PRRedRepairLoop` (rerun + real-red dispatch); DIRTY (merge conflict) → `MergeStateWatcher` + arch-regen self-heal; green-but-unmerged → `DependabotMergeLoop` class-5 path. Before adding a new watcher for an open-PR condition, check which of these three already owns it — see `docs/wiki/patterns.md` entry "Open-PR failure modes each have an owning shepherd loop".
**Why:** prevents duplicate loops competing to fix the same PR state (scope-creep trap called out for issue #10293).
