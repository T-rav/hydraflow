---
id: 0768
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.314845+00:00
status: active
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
---

# Derive git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, build `_invoke_fake_git`'s `"commit"` branch root-commit summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from `git_sandbox` at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** a hardcoded summary silently drifted from real `git commit` output whenever the `git_sandbox` fixture's file set changed, breaking `test_fake_git_matches_cassette[commit]` and `ContractRefreshLoop`'s self-heal cycle.
