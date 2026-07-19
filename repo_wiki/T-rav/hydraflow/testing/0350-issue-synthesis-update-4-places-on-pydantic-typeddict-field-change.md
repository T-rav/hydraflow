---
id: 0350
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.496723+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Update 4 places on Pydantic/TypedDict field changes

When adding or removing fields, update: (1) model definition, (2) test factory defaults, (3) field-presence assertions, (4) serialization round-trip tests.

Example: Grep for the model name: `grep -r "ModelName" tests/`. For `NotRequired` fields, update exact-match assertions but not missing-key assertions. See also: testing — dict-to-TypedDict migrations require no new tests.

**Why:** Missing any location leaves tests that silently ignore the new field, giving false coverage confidence.
