---
id: 0165
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.578130+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Grep all model usages before committing Pydantic or TypedDict changes

Before adding or removing a field, grep the test suite for the model name and update all affected assertions: model definition, factory defaults, `all_fields` tests, and round-trip serialization tests. For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

See also: testing — Type-only annotation changes require no new tests.

**Why:** Missed exact-match assertions silently pass when a field is optional, masking the coverage gap until a stricter test runs later.
