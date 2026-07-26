---
id: 1054
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.519464+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (is_shared_infra) plus one logger.warning call inside an existing loop (adr_reviewer.py's existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test under the ADR-testing standard.

Example: only unit tests across tests/test_adr_drift.py, tests/test_adr_pre_validator.py, tests/test_adr_reviewer.py, plus a tests/regressions/ pin.

**Why:** the docs/standards/testing/README.md full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead the plan explicitly opted out of.
