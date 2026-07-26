---
id: 0032
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:56.231252+00:00
status: active
corroborations: 1
supersedes: 0027,0028,0029,0030,0031
---

# Map cross-dependencies before parallel-extracting a god class

Build a dependency task graph before splitting a god class into multiple coordinators; extract zero-dependency coordinators in parallel, and extract dependents only after their dependency lands.

Example: `ReviewVerdictHandler` depends on `CIFixCoordinator`, so `CIFixCoordinator` must be extracted first — treat this as a task graph, not an assume-all-parallel job.

**Why:** starting parallel extraction without mapping inter-class dependencies causes rework when one extraction turns out to block another.
