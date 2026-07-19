---
id: 0428
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.855136+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
---

# Update 4 places on Pydantic/TypedDict field changes

When adding or removing fields, update: (1) model definition, (2) test factory defaults, (3) field-presence assertions, (4) serialization round-trip tests.

Example: Grep for the model name: `grep -r "ModelName" tests/`. For `NotRequired` fields, update exact-match assertions but not missing-key assertions. See also: testing — dict-to-TypedDict migrations require no new tests.

**Why:** Missing any location leaves tests that silently ignore the new field, giving false coverage confidence.
