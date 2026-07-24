---
id: 0751
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.466584+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (`is_shared_infra`) plus one `logger.warning` call inside an existing loop (`adr_reviewer.py`'s existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test under the ADR-testing standard.

Example: only unit tests across `tests/test_adr_drift.py`, `tests/test_adr_pre_validator.py`, `tests/test_adr_reviewer.py`, plus a `tests/regressions/` pin.

**Why:** the `docs/standards/testing/README.md` full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead the plan explicitly opted out of.
