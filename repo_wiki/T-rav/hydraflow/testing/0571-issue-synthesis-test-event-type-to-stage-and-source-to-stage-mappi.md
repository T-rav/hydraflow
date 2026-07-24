---
id: 0571
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.419444+00:00
status: superseded
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
superseded_by: 0593
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE mappings separately

When testing the ADR-0002 label state machine, assert `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` against `VALID_STAGES` in separate assertions rather than only checking their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one of the two mappings silently omits a new label, since only the union is verified.
