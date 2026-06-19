---
id: 0092
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.277602+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Type-only annotation changes require no new tests

Migrating from `dict[str, Any]` to a `TypedDict` return type, or narrowing a parameter from `Any` to a specific type, requires no new tests — `TypedDict` values are plain dicts at runtime and `Any` is compatible with all types in pyright. Verify via `make quality-lite` and `make test`; the existing suite suffices.

**Why:** Runtime behavior is unchanged; only static validation improves. New tests for type-only changes create maintenance overhead without catching real bugs.
