---
id: 0074
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.272533+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Add structural tests before property-based transition graph tests

Before using hypothesis or similar tools to exercise a label/stage transition graph, add explicit structural assertions: every target is a valid stage, every stage has a transition entry, no dangling references.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

**Why:** Property-based tests on a malformed graph surface as mysterious assertion failures rather than clear 'bad graph definition' errors.
