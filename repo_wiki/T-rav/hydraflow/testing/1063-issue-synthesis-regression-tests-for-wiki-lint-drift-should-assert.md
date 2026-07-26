---
id: 1063
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.548741+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Regression tests for wiki-lint drift should assert the full live-wiki lint

For drift regressions like #10464, write tests/regressions/test_issue_10464.py to assert lint_paraphrases(TermStore(terms).list(), docs/wiki) == [] across the entire live wiki, not just the one flagged term file.

Example: this mirrors and reinforces tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki, and surfaces any other latent paraphrase drift already present on the branch before merge.

**Why:** a narrowly-scoped regression test would pass while leaving other undetected alias collisions to break CI on a later PR.
