---
id: 0163
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.577494+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Assert relative event ID ordering, never absolute values

Tests for events backed by a global counter must assert relative ordering and uniqueness within one test, never absolute ID values.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global ID counters are shared across tests and imports; absolute assertions produce non-deterministic failures under parallel or reordered execution.
