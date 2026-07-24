---
id: 0695
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.866838+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. `tests/regressions/test_issue_10302.py` checking ADR-0017 names `_triage_single_traced`), use word-boundary/whole-token matching, not a substring `in` check.

Example: `_triage_single` is a substring of `_triage_single_traced`, so a stale ADR that only says `_triage_single` would incorrectly pass a substring test; use regex `\b_triage_single\b` vs `\b_triage_single_traced\b` so the two distinct names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
