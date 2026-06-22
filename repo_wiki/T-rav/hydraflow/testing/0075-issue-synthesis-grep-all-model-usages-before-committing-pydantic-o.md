---
id: 0075
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.272803+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Grep all model usages before committing Pydantic or TypedDict changes

Before adding or removing a field, grep the test suite for the model name and update all affected assertions: model definition, factory defaults, `all_fields` tests, and round-trip serialization tests. For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

**Why:** Missed exact-match assertions silently pass when a field is optional, masking the coverage gap until a stricter test runs later.
