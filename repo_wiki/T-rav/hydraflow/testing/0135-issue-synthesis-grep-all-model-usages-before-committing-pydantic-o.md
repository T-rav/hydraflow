---
id: 0135
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.435372+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Grep all model usages before committing Pydantic or TypedDict changes

Before adding or removing a field, grep the test suite for the model name and update all affected assertions: model definition, factory defaults, `all_fields` tests, and round-trip serialization tests. For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

See also: testing — Type-only annotation changes require no new tests.

**Why:** Missed exact-match assertions silently pass when a field is optional, masking the coverage gap until a stricter test runs later.
