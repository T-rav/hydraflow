---
id: 0969
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.558108+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# Exclude `.git` when scanning fixture dirs for contract fakes

Any helper that walks cassette.fixture_repo to build fake git output (e.g. _root_commit_summary() in test_fake_git_contract.py) must filter with ".git" not in p.parts.

Example: include .gitkeep and other dotfiles (no special-casing needed); exclude only the .git/ path segment.

**Why:** a stray .git/ left behind from an in-place record_git run corrupts file/insertion counts in the generated commit summary, since pathlib glob happily includes dotfiles/dotdirs like .gitkeep and .git alike.
