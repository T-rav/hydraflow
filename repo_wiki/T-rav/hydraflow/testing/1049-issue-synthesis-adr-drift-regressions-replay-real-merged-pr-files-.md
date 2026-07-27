---
id: 1049
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.509463+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# ADR-drift regressions replay real merged PR files through production ADRIndex, not fixtures

Pin ADR citation/drift false-positive fixes by driving real inputs through the production ADRIndex and compute_drift/by_adr entry points (src/adr_drift.py + src/adr_index.py) — never a synthetic mock ADR or a stubbed drift engine.

Example: tests/regressions/test_issue_10384.py, test_issue_10411.py, test_issue_9176.py, and test_issue_10531.py replay the actual merged PR file list (e.g. PR #10519's src/implement_phase.py, src/phase_utils.py) through ADRIndex, asserting real source_symbols output and zero findings for a file-only diff. Pair with a tmp_path-fixture ADR that bare-cites a non-exempt module to prove the auditor still fires generally, plus a self-retiring premise guard that skips if the ADR is absent, non-live, or no longer cites the module.

**Why:** a fixture-only or stubbed test can pass while the live ADR/engine regresses or still fires falsely on production diffs, silently reopening the same rollup.
