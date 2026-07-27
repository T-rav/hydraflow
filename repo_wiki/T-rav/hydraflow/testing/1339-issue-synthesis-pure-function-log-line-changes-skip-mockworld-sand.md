---
id: 1339
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.319643+00:00
status: active
corroborations: 1
supersedes: 1265
---

# Pure-function + log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (is_shared_infra) plus one logger.warning call inside an existing loop (adr_reviewer.py's existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test.

Example: only unit tests across tests/test_adr_drift.py, tests/test_adr_pre_validator.py, tests/test_adr_reviewer.py, plus a tests/regressions/ pin. See also: Doc+single-unit-test fixes skip MockWorld/e2e.

**Why:** The docs/standards/testing/README.md full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead.
