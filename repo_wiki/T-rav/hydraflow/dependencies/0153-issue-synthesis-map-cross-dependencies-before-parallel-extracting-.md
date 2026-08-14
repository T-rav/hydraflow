---
id: 0153
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:26:28.550057+00:00
status: active
corroborations: 1
supersedes: 0138
---

# Map cross-dependencies before parallel-extracting a god class

Map a dependency task graph before splitting a god class into coordinators; extract zero-dependency coordinators in parallel, then extract dependents only after their dependency lands.

Example: `ReviewVerdictHandler` depends on `CIFixCoordinator`, so `CIFixCoordinator` must be extracted first — treat this as a task graph, not an assume-all-parallel job.

**Why:** Starting parallel extraction without mapping inter-class dependencies causes rework when one extraction turns out to block another.
