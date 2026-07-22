---
id: 0513
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:10:40.685053+00:00
status: active
corroborations: 1
supersedes: 0500,0501,0502,0503,0504,0505,0506,0507,0508,0509
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE mappings independently

When testing the ADR-0002 label state machine, assert `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` against `VALID_STAGES` in separate assertions rather than only checking their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one of the two mappings silently omits a new label, since only the union is verified.
