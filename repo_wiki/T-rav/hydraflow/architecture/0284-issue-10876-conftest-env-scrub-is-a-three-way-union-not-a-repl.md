---
id: 0284
topic: architecture
source_issue: 10876
source_phase: review
created_at: 2026-07-31T07:50:26.223818+00:00
status: active
corroborations: 1
---

# conftest env scrub is a three-way union, not a replace

Build the test scrub set in `tests/conftest.py` as prefix rule ∪ `declared_env_keys()` ∪ GIT_*/GITHUB_TOKEN. Snapshot env before pop, restore symmetrically in `finally`.

- `HYDRAFLOW_SENTRY_DISABLED` is reseeded via `test_env` and must survive the scrub cycle.
- Ambient `SENTRY_AUTH_TOKEN` was caught leaking by this exact pattern.

**Why:** Narrowing or replacing the scrub set re-opens ambient env leaks the original isolation was designed to catch.
