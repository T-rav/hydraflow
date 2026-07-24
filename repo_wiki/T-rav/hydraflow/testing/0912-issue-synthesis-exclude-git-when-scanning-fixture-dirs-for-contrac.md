---
id: 0912
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:41:31.158932+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks `cassette.fixture_repo` to build fake git output (e.g. `_root_commit_summary()` in `test_fake_git_contract.py`) must filter with `".git" not in p.parts`.

Example: include `.gitkeep` and other dotfiles (no special-casing needed); exclude only the `.git/` path segment.

**Why:** a stray `.git/` left behind from an in-place `record_git` run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like `.gitkeep` and `.git` alike.
