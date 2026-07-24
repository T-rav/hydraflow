---
id: 0727
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.209969+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks `cassette.fixture_repo` to build fake git output (e.g. `_root_commit_summary()` in `test_fake_git_contract.py`) must filter with `".git" not in p.parts`.

Example: include `.gitkeep` and other dotfiles (no special-casing needed); exclude only the `.git/` path segment.

**Why:** a stray `.git/` left behind from an in-place `record_git` run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like `.gitkeep` and `.git` alike.
