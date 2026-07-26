---
id: 1038
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.483592+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. tests/regressions/test_issue_10302.py checking ADR-0017 names _triage_single_traced), use word-boundary/whole-token matching, not a substring `in` check.

Example: _triage_single is a substring of _triage_single_traced, so a stale ADR that only says _triage_single would incorrectly pass a substring test; use regex \b_triage_single\b vs \b_triage_single_traced\b so the two distinct names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
