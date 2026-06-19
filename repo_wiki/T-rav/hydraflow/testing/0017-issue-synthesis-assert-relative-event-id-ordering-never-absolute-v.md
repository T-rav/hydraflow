---
id: 0017
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.828947+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Assert relative event ID ordering, never absolute values

Tests for events backed by a global counter (`_event_counter`) must assert relative ordering and uniqueness within one test, never absolute ID values.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global ID counters are shared across tests and imports; absolute assertions produce non-deterministic failures under parallel or reordered execution.
