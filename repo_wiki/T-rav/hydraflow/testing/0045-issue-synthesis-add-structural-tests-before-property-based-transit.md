---
id: 0045
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.212373+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Add structural tests before property-based transition graph tests

Before using hypothesis or similar tools to exercise a label/stage transition graph, add explicit structural assertions: every target is a valid stage, every stage has a transition entry, no dangling references.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

**Why:** Property-based tests on a malformed graph surface as mysterious assertion failures rather than clear "bad graph definition" errors.
