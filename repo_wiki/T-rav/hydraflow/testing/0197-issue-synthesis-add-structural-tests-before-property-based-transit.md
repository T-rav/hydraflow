---
id: 0197
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.787682+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Add structural tests before property-based transition graph tests

Before using hypothesis or similar tools to exercise a label/stage transition graph, add explicit structural assertions: every target is a valid stage, every stage has a transition entry, no dangling references.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

**Why:** Property-based tests on a malformed graph surface as mysterious assertion failures rather than clear "bad graph definition" errors.
