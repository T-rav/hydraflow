---
id: 0026
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.410673+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Pydantic/TypedDict field changes require updates in 4 places

When adding or removing fields, update: (1) model definition, (2) test factory defaults, (3) field-presence assertions, (4) serialization round-trip tests.

Before committing, grep for the model name: `grep -r "ModelName" tests/`.

**Why:** Missing any location leaves tests that silently ignore the new field, giving false coverage confidence.
