---
id: 0105
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.082823+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Grep all model usages before committing Pydantic or TypedDict changes

Before adding or removing a field, grep the test suite for the model name and update all affected assertions: model definition, factory defaults, `all_fields` tests, and round-trip serialization tests. For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

See also: testing — Type-only annotation changes require no new tests.

**Why:** Missed exact-match assertions silently pass when a field is optional, masking the coverage gap until a stricter test runs later.
