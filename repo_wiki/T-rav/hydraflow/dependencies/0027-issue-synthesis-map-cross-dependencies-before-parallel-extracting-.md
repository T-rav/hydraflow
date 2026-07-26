---
id: 0027
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:53:24.581277+00:00
status: superseded
corroborations: 1
supersedes: 0022,0023,0024,0025,0026
superseded_by: 0032
---

# Map cross-dependencies before parallel-extracting a god class

Build a dependency task graph before splitting a god class into multiple coordinators; extract zero-dependency coordinators in parallel, and extract dependents only after their dependency lands.

Example: `ReviewVerdictHandler` depends on `CIFixCoordinator`, so `CIFixCoordinator` must be extracted first — treat this as a task graph, not an assume-all-parallel job.

**Why:** starting parallel extraction without mapping inter-class dependencies causes rework when one extraction turns out to block another.
