---
id: 0726
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.208755+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# Derive git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, build `_invoke_fake_git`'s `"commit"` branch root-commit summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from `git_sandbox` at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** a hardcoded summary silently drifted from real `git commit` output whenever the `git_sandbox` fixture's file set changed, breaking `test_fake_git_matches_cassette[commit]` and `ContractRefreshLoop`'s self-heal cycle.
