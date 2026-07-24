---
id: 0920
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:41:31.175553+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. `tests/regressions/test_issue_10302.py` checking ADR-0017 names `_triage_single_traced`), use word-boundary/whole-token matching, not a substring `in` check.

Example: `_triage_single` is a substring of `_triage_single_traced`, so a stale ADR that only says `_triage_single` would incorrectly pass a substring test; use regex `\b_triage_single\b` vs `\b_triage_single_traced\b` so the two distinct names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
