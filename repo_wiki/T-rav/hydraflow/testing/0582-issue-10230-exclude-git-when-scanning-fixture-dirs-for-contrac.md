---
id: 0582
topic: testing
source_issue: 10230
source_phase: plan
created_at: 2026-07-22T18:13:39.968068+00:00
status: superseded
corroborations: 1
superseded_by: 0593
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks `cassette.fixture_repo` to build fake git output (e.g. `_root_commit_summary()` in `test_fake_git_contract.py`) must filter with `".git" not in p.parts`. A stray `.git/` left behind from an in-place `record_git` run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like `.gitkeep` and `.git` alike.

- Include: `.gitkeep` and other dotfiles (no special-casing needed).
- Exclude: `.git/` path segment specifically.

**Why:** an untracked `.git/` from a prior manual recorder run silently inflates the fake's file count and breaks cassette parity.
