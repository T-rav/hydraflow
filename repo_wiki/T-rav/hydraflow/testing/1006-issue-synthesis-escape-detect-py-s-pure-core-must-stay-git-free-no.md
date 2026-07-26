---
id: 1006
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.604373+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# escape/detect.py's pure core must stay git-free — no subprocess/gh/git calls

src/escape/detect.py is designed as a pure, git-free detector: classification logic (like the has_skip_regression gate and _origin_pointer) must only operate on already-extracted commit data, never shell out to git/gh/subprocess.

Example: test layering enforces this — tests/test_escape_ledger.py is unit-level pure-function tests, while tests/scenarios/test_escape_ledger_scenario.py uses MockWorld fakes only, no real git/GitHub/subprocess calls even at the scenario layer. Regression spec tests/regressions/test_issue_10498.py is written red-first and must be run to confirm 2/2 FAIL before touching src/.

**Why:** keeping the detector pure lets it be unit-tested deterministically and reused by callers (like audit.crosslink) without pulling in process/network dependencies.
