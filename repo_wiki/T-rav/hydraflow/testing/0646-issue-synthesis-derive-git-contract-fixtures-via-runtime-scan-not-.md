---
id: 0646
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.493072+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
---

# Derive git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, `_invoke_fake_git`'s `"commit"` branch previously built its root-commit summary from a hardcoded f-string. When the `git_sandbox` fixture's file set changed, the fake's output silently drifted from real `git commit` output and `test_fake_git_matches_cassette[commit]` broke `ContractRefreshLoop`'s self-heal cycle.

Example: derive the summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time (file list + per-file insertion counts), so fake output stays in lockstep with fixture contents automatically.

**Why:** prevents this failure class from recurring every time someone edits the `git_sandbox` fixture.
