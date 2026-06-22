---
id: 0164
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.577810+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Add structural tests before property-based transition graph tests

Before using hypothesis or similar tools to exercise a label/stage transition graph, add explicit structural assertions: every target is a valid stage, every stage has a transition entry, no dangling references.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

**Why:** Property-based tests on a malformed graph surface as mysterious assertion failures rather than clear 'bad graph definition' errors.
