---
id: 1090
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:44:02.114200+00:00
status: superseded
corroborations: 1
supersedes: 0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952,0953,0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014,1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1031,1032,1033,1034,1035,1036
superseded_by: 1144
---

# Scope-guard tactical allowlist PRs to exact diff to avoid parent stall

When splitting a tactical fix off a stalled/broader parent issue (e.g. #10455 sliced from #10411's validated commit 92c9a12c), enforce the diff at review to just the two string literals plus a lineage comment in `src/adr_drift.py` and the new test file — widening into `_citation_drifts`, config, or the resolver loop reintroduces the complexity that stalled the parent.

**Why:** Scope creep back into the resolver is the exact failure mode the tactical split was meant to avoid.
