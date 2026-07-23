---
id: 0311
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.012272+00:00
status: superseded
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
superseded_by: 0334
---

# Pydantic/TypedDict field changes require updates in 4 places

When adding or removing fields, update: (1) model definition, (2) test factory defaults, (3) field-presence assertions, (4) serialization round-trip tests.

Example: Grep for the model name: `grep -r "ModelName" tests/`. For `NotRequired` fields, update exact-match assertions but not missing-key assertions. See also: testing — dict-to-TypedDict migrations require no new tests.

**Why:** Missing any location leaves tests that silently ignore the new field, giving false coverage confidence.
