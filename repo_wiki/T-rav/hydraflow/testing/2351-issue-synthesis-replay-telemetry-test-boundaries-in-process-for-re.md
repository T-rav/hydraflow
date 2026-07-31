---
id: 2351
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.105943+00:00
status: active
corroborations: 1
supersedes: 2207
---

# Replay telemetry test boundaries in-process for regression tests

Write regression tests for telemetry state leaks by driving the test boundary in-process. `tests/regressions/test_issue_10903.py` should manually trigger the real `conftest` teardown. Construct provider A, emit a span, run teardown, construct provider B, and assert B captures the span.

**Why:** Relying on pytest collection order to reproduce leaks is flaky; driving the boundary in-process deterministically reproduces the global state leak.
