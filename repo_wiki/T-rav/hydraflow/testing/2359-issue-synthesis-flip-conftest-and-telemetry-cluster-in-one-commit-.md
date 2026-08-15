---
id: 2359
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.127628+00:00
status: superseded
corroborations: 1
supersedes: 2217
superseded_by: 2548
---

# Flip conftest and telemetry cluster in one commit or reset inverts

When fixing the dual-alias bug, `tests/conftest.py` and all telemetry/OTel test files (`test_telemetry_*.py`, `test_base_runner_telemetry.py`, `test_telemetry_e2e.py`, `test_otel_disabled_is_noop.py`) must land in a single commit.

Example: once conftest clears the bare-alias cache, any test still bound to `src.` loses its reset coverage.

**Why:** Splitting across PRs inverts which alias gets reset — the suite goes flaky under xdist rather than red, making the regression invisible in serial CI.
