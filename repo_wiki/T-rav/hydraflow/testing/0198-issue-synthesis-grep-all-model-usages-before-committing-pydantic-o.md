---
id: 0198
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.788034+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Grep all model usages before committing Pydantic or TypedDict changes

Before adding or removing a field, grep the test suite for the model name and update all affected assertions: model definition, factory defaults, `all_fields` tests, and round-trip serialization tests. For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

See also: testing — Type-only annotation changes require no new tests.

**Why:** Missed exact-match assertions silently pass when a field is optional, masking coverage gaps until a stricter test runs.
