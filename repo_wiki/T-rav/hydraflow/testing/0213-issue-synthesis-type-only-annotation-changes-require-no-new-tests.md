---
id: 0213
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.793210+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Type-only annotation changes require no new tests

Migrating from `dict[str, Any]` to a `TypedDict` return type, or narrowing a parameter from `Any` to a specific type, requires no new tests — `TypedDict` values are plain dicts at runtime. Verify via `make quality-lite` and `make test`; the existing suite suffices.

See also: testing — Grep all model usages before committing Pydantic or TypedDict changes.

**Why:** Runtime behavior is unchanged; new tests for type-only changes create maintenance overhead without catching real bugs.
