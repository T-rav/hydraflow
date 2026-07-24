---
id: 0608
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.583298+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks `cassette.fixture_repo` to build fake git output (e.g. `_root_commit_summary()` in `test_fake_git_contract.py`) must filter with `".git" not in p.parts`. A stray `.git/` left behind from an in-place `record_git` run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like `.gitkeep` and `.git` alike.

- Include: `.gitkeep` and other dotfiles (no special-casing needed).
- Exclude: `.git/` path segment specifically.

**Why:** an untracked `.git/` from a prior manual recorder run silently inflates the fake's file count and breaks cassette parity.
