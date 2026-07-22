---
id: 0546
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.121889+00:00
status: active
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE mappings separately

When testing the ADR-0002 label state machine, assert `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` against `VALID_STAGES` in separate assertions rather than only checking their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one of the two mappings silently omits a new label, since only the union is verified.
