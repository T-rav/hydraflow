---
id: 2090
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.178919+00:00
status: superseded
corroborations: 1
supersedes: 1960
superseded_by: 2235
---

# Test EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE separately

When testing the ADR-0002 label state machine, assert EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE against VALID_STAGES in separate assertions, not only their combined union.

Example: two distinct parametrized checks, one per mapping's keys.

**Why:** A combined check can pass while one mapping silently omits a new label.
