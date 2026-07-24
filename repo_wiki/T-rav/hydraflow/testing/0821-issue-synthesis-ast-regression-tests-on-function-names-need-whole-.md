---
id: 0821
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.196462+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. `tests/regressions/test_issue_10302.py` checking ADR-0017 names `_triage_single_traced`), use word-boundary/whole-token matching, not a substring `in` check.

Example: `_triage_single` is a substring of `_triage_single_traced`, so a stale ADR that only says `_triage_single` would incorrectly pass a substring test; use regex `\b_triage_single\b` vs `\b_triage_single_traced\b` so the two distinct names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
