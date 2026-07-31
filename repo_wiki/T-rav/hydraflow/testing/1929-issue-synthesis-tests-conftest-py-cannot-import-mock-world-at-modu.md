---
id: 1929
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.598201+00:00
status: active
corroborations: 1
supersedes: 1825
---

# tests/conftest.py cannot import mock_world at module scope

`tests.scenarios.fakes.mock_world` imports `tests.conftest.TaskFactory`, so importing `mock_world` at the top of `tests/conftest.py` creates a circular import that breaks all collection.

Example: in `tests/conftest.py`, reach the live-world drain via `sys.modules['tests.scenarios.fakes.mock_world'].close_open_worlds` resolved inside the fixture body, never a top-level import.

**Why:** An eager import would fail collection before any test runs; the deferred lookup keeps `TaskFactory` available to `mock_world` while still wiring the autouse teardown.
