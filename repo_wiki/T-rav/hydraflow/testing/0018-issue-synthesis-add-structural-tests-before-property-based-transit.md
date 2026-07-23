---
id: 0018
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.829118+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Add structural tests before property-based transition graph tests

Before using hypothesis or similar tools to exercise a label/stage transition graph, add explicit structural assertions: every target is a valid stage, every stage has a transition entry, no dangling references.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

**Why:** Property-based tests on a malformed graph surface as mysterious assertion failures rather than clear "bad graph definition" errors.
