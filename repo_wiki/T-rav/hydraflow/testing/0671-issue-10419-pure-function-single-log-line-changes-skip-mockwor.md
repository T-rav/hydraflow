---
id: 0671
topic: testing
source_issue: 10419
source_phase: plan
created_at: 2026-07-24T07:06:01.754996+00:00
status: superseded
corroborations: 1
superseded_by: 0672
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (`is_shared_infra`) plus one `logger.warning` call inside an existing loop (`adr_reviewer.py`'s existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test under the ADR-testing standard — only unit tests across `tests/test_adr_drift.py`, `tests/test_adr_pre_validator.py`, `tests/test_adr_reviewer.py`, plus a `tests/regressions/` pin. Reserve the full three-layer pyramid for changes that cross phases or touch orchestrator/state behavior.
**Why:** the `docs/standards/testing/README.md` full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead the plan explicitly opted out of.
