---
id: 1003
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.600599+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# `_in_retry_window()` regression coverage lives in test_issue_10459.py

Production behavior for _in_retry_window() in src/workspace_gc_loop.py is already covered by tests/regressions/test_issue_10459.py; when a browser/scenario test fails against this function, treat it as test-side drift and fix the mock, not the production code or add new unit tests.

Example: if a fix here seems to require touching src/, that's a signal the scope has grown beyond test drift and needs re-scoping.

**Why:** keeps regression coverage centralized in one place instead of duplicating retry-window assertions across scenario layers.
