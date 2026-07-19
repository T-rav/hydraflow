---
id: 0075
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.533603+00:00
status: superseded
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
superseded_by: 0092
---

# Define EVENT_TO_STAGE and SOURCE_TO_STAGE mappings before skip detection

Implement event/worker-to-stage mappings together with skip detection logic — never add a mapping after skip detection is wired.

Example: define `EVENT_TO_STAGE = {...}` and `SOURCE_TO_STAGE = {...}` before the `if event in skip_set: return` guard.

**Why:** Mappings added after the early-return guard are never evaluated, making the new stage silently unreachable.
