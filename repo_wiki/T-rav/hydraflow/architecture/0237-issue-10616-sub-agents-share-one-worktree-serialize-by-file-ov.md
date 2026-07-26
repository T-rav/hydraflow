---
id: 0237
topic: architecture
source_issue: 10616
source_phase: plan
created_at: 2026-07-26T11:05:04.471690+00:00
status: active
corroborations: 1
---

# Sub-agents share one worktree; serialize by file overlap

HydraFlow `Task` sub-agents operate in the same worktree — there are no per-agent branches. When grouping build phases into parallel waves, never schedule two agents onto the same file. File-overlap serialization *is* the conflict-avoidance mechanism.

`parallel_waves(phases)` in `src/build_strategy.py` must split dependency-free phases that touch the same file into separate waves. Dependency edges (`Depends on:`) are a second scheduling constraint layered on top.

**Why:** Without file-overlap serialization, concurrent sub-agents corrupt shared files in the single shared worktree.
