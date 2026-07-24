---
id: 0590
topic: testing
source_issue: 10302
source_phase: plan
created_at: 2026-07-24T03:55:54.536766+00:00
status: superseded
corroborations: 1
superseded_by: 0593
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. `tests/regressions/test_issue_10302.py` checking ADR-0017 names `_triage_single_traced`), a naive substring `in` check will false-positive: `_triage_single` is a substring of `_triage_single_traced`, so a stale ADR that only says `_triage_single` would incorrectly pass a substring test. Use word-boundary/whole-token matching (e.g. regex `\b_triage_single\b` vs `\b_triage_single_traced\b`) so the two distinct function names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
