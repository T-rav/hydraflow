---
id: 1058
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.534835+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on ADR-0049 (docs/adr/0049-trust-loop-kill-switch-convention.md), the regression test lives in tests/regressions/test_issue_10444.py and asserts against parse_adr_file() output — that source_files includes src/base_background_loop.py and src/bg_worker_manager.py, and source_symbols maps them to LoopDeps / BGWorkerManager.is_enabled respectively.

Example: classified as not-load-bearing (no pipeline/runner/loop change), so per docs/standards/testing/README.md it skips MockWorld scenario and sandbox e2e.

**Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
