---
id: 0019
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.829281+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Grep all model usages before committing Pydantic or TypedDict field changes

Before adding or removing a field, grep the test suite for the model name and update all affected assertions: model definition, factory defaults, `all_fields` tests, and round-trip serialization tests.

For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

**Why:** Missed exact-match assertions silently pass when the field is optional, masking the coverage gap until a stricter test runs later.
