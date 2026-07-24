---
id: 0636
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.484148+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE mappings separately

When testing the ADR-0002 label state machine, assert `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` against `VALID_STAGES` in separate assertions rather than only checking their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one of the two mappings silently omits a new label, since only the union is verified.
