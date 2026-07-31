---
id: 1825
topic: testing
source_issue: 10875
source_phase: plan
created_at: 2026-07-31T03:41:38.628273+00:00
status: superseded
corroborations: 1
superseded_by: 1929
---

# tests/conftest.py cannot import mock_world at module scope (TaskFactory cycle)

`tests.scenarios.fakes.mock_world` imports `tests.conftest.TaskFactory`, so importing `mock_world` at the top of `tests/conftest.py` creates a circular import that breaks all collection.

Rule: in `tests/conftest.py`, reach the live-world drain via `sys.modules['tests.scenarios.fakes.mock_world'].close_open_worlds` resolved inside the fixture body, never a top-level import.

**Why:** an eager import would fail collection before any test runs; the deferred lookup keeps `TaskFactory` available to `mock_world` while still wiring the autouse teardown.
