---
id: 0196
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.787334+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Assert relative event ID ordering, never absolute values

Tests for events backed by a global counter must assert relative ordering and uniqueness within one test, never absolute ID values.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global ID counters are shared across tests and imports; absolute assertions produce non-deterministic failures under parallel or reordered execution.
