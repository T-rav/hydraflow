---
id: 0977
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.568007+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. tests/regressions/test_issue_10302.py checking ADR-0017 names _triage_single_traced), use word-boundary/whole-token matching, not a substring `in` check.

Example: _triage_single is a substring of _triage_single_traced, so a stale ADR that only says _triage_single would incorrectly pass a substring test; use regex \b_triage_single\b vs \b_triage_single_traced\b so the two distinct names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
