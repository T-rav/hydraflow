---
id: 0038
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:32.728989+00:00
status: superseded
corroborations: 1
supersedes: 0032
superseded_by: 0044
---

# Map cross-dependencies before parallel-extracting a god class

Build a dependency task graph before splitting a god class into multiple coordinators; extract zero-dependency coordinators in parallel, and extract dependents only after their dependency lands.

Example: `ReviewVerdictHandler` depends on `CIFixCoordinator`, so `CIFixCoordinator` must be extracted first — treat this as a task graph, not an assume-all-parallel job.

**Why:** Starting parallel extraction without mapping inter-class dependencies causes rework when one extraction turns out to block another.
