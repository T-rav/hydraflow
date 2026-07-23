---
id: 0468
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.353444+00:00
status: superseded
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
superseded_by: 0492
---

# Update 4 places on Pydantic/TypedDict field changes

When adding or removing fields, update: (1) model definition, (2) test factory defaults, (3) field-presence assertions, (4) serialization round-trip tests.

Example: Grep for the model name: `grep -r "ModelName" tests/`. For `NotRequired` fields, update exact-match assertions but not missing-key assertions. See also: testing — dict-to-TypedDict migrations require no new tests.

**Why:** Missing any location leaves tests that silently ignore the new field, giving false coverage confidence.
