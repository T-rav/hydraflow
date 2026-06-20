---
id: 0133
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.434788+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Assert relative event ID ordering, never absolute values

Tests for events backed by a global counter (`_event_counter`) must assert relative ordering and uniqueness within one test, never absolute ID values.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global ID counters are shared across tests and imports; absolute assertions produce non-deterministic failures under parallel or reordered execution.
