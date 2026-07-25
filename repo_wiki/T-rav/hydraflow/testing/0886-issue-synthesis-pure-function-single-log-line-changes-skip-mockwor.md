---
id: 0886
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.560747+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0897
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (`is_shared_infra`) plus one `logger.warning` call inside an existing loop (`adr_reviewer.py`'s existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test under the ADR-testing standard.

Example: only unit tests across `tests/test_adr_drift.py`, `tests/test_adr_pre_validator.py`, `tests/test_adr_reviewer.py`, plus a `tests/regressions/` pin.

**Why:** the `docs/standards/testing/README.md` full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead the plan explicitly opted out of.
