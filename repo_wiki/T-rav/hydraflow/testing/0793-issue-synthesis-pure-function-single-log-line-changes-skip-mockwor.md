---
id: 0793
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.369505+00:00
status: active
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (`is_shared_infra`) plus one `logger.warning` call inside an existing loop (`adr_reviewer.py`'s existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test under the ADR-testing standard.

Example: only unit tests across `tests/test_adr_drift.py`, `tests/test_adr_pre_validator.py`, `tests/test_adr_reviewer.py`, plus a `tests/regressions/` pin.

**Why:** the `docs/standards/testing/README.md` full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead the plan explicitly opted out of.
