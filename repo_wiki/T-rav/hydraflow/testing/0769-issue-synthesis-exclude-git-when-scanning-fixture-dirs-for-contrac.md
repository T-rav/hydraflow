---
id: 0769
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.316605+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks `cassette.fixture_repo` to build fake git output (e.g. `_root_commit_summary()` in `test_fake_git_contract.py`) must filter with `".git" not in p.parts`.

Example: include `.gitkeep` and other dotfiles (no special-casing needed); exclude only the `.git/` path segment.

**Why:** a stray `.git/` left behind from an in-place `record_git` run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like `.gitkeep` and `.git` alike.
