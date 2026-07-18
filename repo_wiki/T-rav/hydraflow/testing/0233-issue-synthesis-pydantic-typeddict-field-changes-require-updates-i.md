---
id: 0233
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:19:21.284594+00:00
status: active
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
---

# Pydantic/TypedDict field changes require updates in 4 places

When adding or removing fields, update: (1) model definition, (2) test factory defaults, (3) field-presence assertions, (4) serialization round-trip tests.

Before committing, grep for the model name: `grep -r "ModelName" tests/`. For `NotRequired` fields, update exact-match assertions but not missing-key assertions.

See also: testing — dict-to-TypedDict migrations require no new tests.

**Why:** Missing any location leaves tests that silently ignore the new field, giving false coverage confidence.
