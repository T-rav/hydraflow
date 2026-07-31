---
id: 1551
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.302622+00:00
status: superseded
corroborations: 1
supersedes: 1469
superseded_by: 1634
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE separately

When testing the ADR-0002 label state machine, assert EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE against VALID_STAGES in separate assertions, not only their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one mapping silently omits a new label.
