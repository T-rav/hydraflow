---
id: 0616
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.590501+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. `tests/regressions/test_issue_10302.py` checking ADR-0017 names `_triage_single_traced`), a naive substring `in` check will false-positive: `_triage_single` is a substring of `_triage_single_traced`, so a stale ADR that only says `_triage_single` would incorrectly pass a substring test. Use word-boundary/whole-token matching (e.g. regex `\b_triage_single\b` vs `\b_triage_single_traced\b`) so the two distinct function names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
