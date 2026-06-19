---
id: 0182
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.583920+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Type-only annotation changes require no new tests

Migrating from `dict[str, Any]` to a `TypedDict` return type, or narrowing a parameter from `Any` to a specific type, requires no new tests — `TypedDict` values are plain dicts at runtime. Verify via `make quality-lite` and `make test`; the existing suite suffices.

See also: testing — Grep all model usages before committing Pydantic or TypedDict changes.

**Why:** Runtime behavior is unchanged; only static validation improves. New tests for type-only changes create maintenance overhead without catching real bugs.
