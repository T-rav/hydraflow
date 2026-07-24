---
id: 0006
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:33:02.550180+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005
---

# Map cross-dependencies before parallel-extracting a god class

When extracting multiple coordinators from a god class, first identify which have zero cross-dependencies and extract those in parallel; extract dependent ones only after their dependency is done.
Example: `ReviewVerdictHandler` depends on `CIFixCoordinator`, so `CIFixCoordinator` must be extracted before `ReviewVerdictHandler` — map these as a task graph rather than assuming all extractions are parallelizable.
**Why:** starting parallel extraction without mapping inter-class dependencies causes rework when one extraction turns out to block another.
