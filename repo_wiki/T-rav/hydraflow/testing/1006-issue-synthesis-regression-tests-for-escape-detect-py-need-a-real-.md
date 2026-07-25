---
id: 1006
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.163450+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# Regression tests for escape/detect.py need a real temp git repo

`tests/test_escape_ledger.py` feeds `added_paths` to `_classify` synthetically, which cannot catch bugs in the git-adapter parse layer (`_added_paths_for_range`, `commits_for_range`) upstream of classification. `tests/regressions/test_issue_10499.py` instead drives `commits_for_range` against a real temp git repo whose commit adds `tests/regressions/x.py`, asserting `added_paths` is non-empty and correctly attributed per-commit, not merged across a multi-commit range.

**Why:** synthetic-input unit tests exercise `_classify` correctly but leave the marker-parsing path (`_SHA_MARKER`, `out.splitlines()`) completely uncovered — exactly how this escaped to production.
