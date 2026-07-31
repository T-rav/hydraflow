---
id: 2217
topic: testing
source_issue: 10906
source_phase: plan
created_at: 2026-07-31T12:53:04.027150+00:00
status: active
corroborations: 1
---

# Flip conftest and telemetry cluster in one commit or reset inverts

When fixing the dual-alias bug, `tests/conftest.py` and all telemetry/OTel test files (`test_telemetry_*.py`, `test_base_runner_telemetry.py`, `test_telemetry_e2e.py`, `test_otel_disabled_is_noop.py`) must land in a single commit. Once conftest clears the bare-alias cache, any test still bound to `src.` loses its reset coverage.

**Why:** Splitting across PRs inverts which alias gets reset — the suite goes flaky under xdist rather than red, making the regression invisible in serial CI.
