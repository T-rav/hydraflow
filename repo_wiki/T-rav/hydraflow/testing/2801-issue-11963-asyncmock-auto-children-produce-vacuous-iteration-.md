---
id: 2801
topic: testing
source_issue: 11963
source_phase: plan
created_at: 2026-09-01T09:53:18.676805+00:00
status: active
corroborations: 1
---

# AsyncMock auto-children produce vacuous iteration in test fixtures

When mocking `PRPort` in the `env` fixture for `MemoryBacklogLoop` tests, set `pr.list_issues_by_label` to an explicit `AsyncMock` with a configured return value.

- Auto-children return `MagicMock`, whose `__iter__` is vacuously empty.
- This masks matcher bugs: `find_citing_issue` loops over summaries and silently returns `None` for every entry.

**Why:** Vacuous iteration makes the durable guard appear to work when it actually never sees any issues, producing false-green tests.
