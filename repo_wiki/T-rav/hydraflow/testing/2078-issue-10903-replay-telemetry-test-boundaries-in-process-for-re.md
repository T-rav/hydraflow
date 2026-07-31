---
id: 2078
topic: testing
source_issue: 10903
source_phase: plan
created_at: 2026-07-31T11:47:02.704743+00:00
status: superseded
corroborations: 1
superseded_by: 2207
---

# Replay telemetry test boundaries in-process for regression tests

Write regression tests for telemetry state leaks by driving the test boundary in-process. `tests/regressions/test_issue_10903.py` should manually trigger the real `conftest` teardown. Construct provider A, emit a span, run teardown, construct provider B, and assert B captures the span. **Why:** Relying on pytest collection order to reproduce leaks is flaky; driving the boundary in-process deterministically reproduces the global state leak.
