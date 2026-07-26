---
id: 0022
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:40.534575+00:00
status: superseded
corroborations: 1
supersedes: 0017,0018,0019,0020,0021
superseded_by: 0027
---

# Map cross-dependencies before parallel-extracting a god class

Before splitting a god class into multiple coordinators, build a dependency task graph and extract zero-dependency coordinators in parallel; extract dependents only after their dependency lands.

Example: `ReviewVerdictHandler` depends on `CIFixCoordinator`, so `CIFixCoordinator` must be extracted first — treat this as a task graph, not an assume-all-parallel job.

**Why:** starting parallel extraction without mapping inter-class dependencies causes rework when one extraction turns out to block another.
