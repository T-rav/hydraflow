---
id: 1070
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.558903+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Consult hydraflow-review-advisor before escalating finding severity

Before finalizing severity on findings like "missing fake-vs-real parity test," run them past the hydraflow-review-advisor subagent — in #10515 it correctly downgraded two initial concerns (missing parity test, "padding" diagrams) that were actually already covered by existing tests (tests/test_issue_store.py:1122, :1732) or established repo convention (per-issue .likec4 diagrams are common, not PR-specific bloat).

**Why:** prevents overstating severity from an incomplete read of existing coverage/conventions before verifying against the advisor or the actual test suite.
