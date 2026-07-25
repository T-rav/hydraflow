---
id: 1009
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.608130+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Consult hydraflow-review-advisor before escalating finding severity

Before finalizing severity on findings like "missing fake-vs-real parity test," run them past the hydraflow-review-advisor subagent — in #10515 it correctly downgraded two initial concerns (missing parity test, "padding" diagrams) that were actually already covered by existing tests (tests/test_issue_store.py:1122, :1732) or established repo convention (per-issue .likec4 diagrams are common, not PR-specific bloat).

**Why:** prevents overstating severity from an incomplete read of existing coverage/conventions before verifying against the advisor or the actual test suite.
