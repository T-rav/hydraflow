---
id: 0122
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.088348+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Type-only annotation changes require no new tests

Migrating from `dict[str, Any]` to a `TypedDict` return type, or narrowing a parameter from `Any` to a specific type, requires no new tests — `TypedDict` values are plain dicts at runtime and `Any` is compatible with all types in pyright. Verify via `make quality-lite` and `make test`; the existing suite suffices.

See also: testing — Grep all model usages before committing Pydantic or TypedDict changes.

**Why:** Runtime behavior is unchanged; only static validation improves. New tests for type-only changes create maintenance overhead without catching real bugs.
