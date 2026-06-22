---
id: 0152
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.440475+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Type-only annotation changes require no new tests

Migrating from `dict[str, Any]` to a `TypedDict` return type, or narrowing a parameter from `Any` to a specific type, requires no new tests — `TypedDict` values are plain dicts at runtime and `Any` is compatible with all types in pyright. Verify via `make quality-lite` and `make test`; the existing suite suffices.

See also: testing — Grep all model usages before committing Pydantic or TypedDict changes.

**Why:** Runtime behavior is unchanged; only static validation improves. New tests for type-only changes create maintenance overhead without catching real bugs.
