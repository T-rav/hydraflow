---
id: 0062
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.215274+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Type-only annotation changes require no new tests

Migrating from `dict[str, Any]` to a `TypedDict` return type, or narrowing a parameter from `Any` to a specific type, requires no new tests — `TypedDict` values are plain dicts at runtime and `Any` is compatible with all types in pyright.

Verify via `make quality-lite` and `make test`; the existing suite suffices.

**Why:** Runtime behavior is unchanged; only static validation improves. New tests for type-only changes create maintenance overhead without catching real bugs.
