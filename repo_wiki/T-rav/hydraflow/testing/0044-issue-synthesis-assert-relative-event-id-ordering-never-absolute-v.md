---
id: 0044
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.212214+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Assert relative event ID ordering, never absolute values

Tests for events backed by a global counter (`_event_counter`) must assert relative ordering and uniqueness within one test, never absolute ID values.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global ID counters are shared across tests and imports; absolute assertions produce non-deterministic failures under parallel or reordered execution.
