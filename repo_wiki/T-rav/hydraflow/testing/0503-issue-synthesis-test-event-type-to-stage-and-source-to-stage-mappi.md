---
id: 0503
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:43:13.306382+00:00
status: superseded
corroborations: 1
supersedes: 0492,0493,0494,0495,0496,0497,0498,0499
superseded_by: 0510
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE mappings independently

When testing the ADR-0002 label state machine, assert `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` against `VALID_STAGES` in separate assertions rather than only checking their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one of the two mappings silently omits a new label, since only the union is verified.
