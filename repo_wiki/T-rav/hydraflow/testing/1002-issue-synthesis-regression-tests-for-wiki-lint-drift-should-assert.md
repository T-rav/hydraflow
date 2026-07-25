---
id: 1002
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.599362+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Regression tests for wiki-lint drift should assert the full live-wiki lint

For drift regressions like #10464, write tests/regressions/test_issue_10464.py to assert lint_paraphrases(TermStore(terms).list(), docs/wiki) == [] across the entire live wiki, not just the one flagged term file.

Example: this mirrors and reinforces tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki, and surfaces any other latent paraphrase drift already present on the branch before merge.

**Why:** a narrowly-scoped regression test would pass while leaving other undetected alias collisions to break CI on a later PR.
