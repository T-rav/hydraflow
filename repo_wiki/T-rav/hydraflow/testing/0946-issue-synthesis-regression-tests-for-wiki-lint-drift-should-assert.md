---
id: 0946
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.998044+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# Regression tests for wiki-lint drift should assert the full live-wiki lint

For drift regressions like #10464, write `tests/regressions/test_issue_10464.py` to assert `lint_paraphrases(TermStore(terms).list(), docs/wiki) == []` across the entire live wiki, not just the one flagged term file.

Example: this mirrors and reinforces `tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki`, and surfaces any other latent paraphrase drift already present on the branch before merge.

**Why:** a narrowly-scoped regression test would pass while leaving other undetected alias collisions to break CI on a later PR.
