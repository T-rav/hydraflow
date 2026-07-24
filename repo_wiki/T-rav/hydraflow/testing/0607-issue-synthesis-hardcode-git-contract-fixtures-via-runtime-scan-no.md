---
id: 0607
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.582392+00:00
status: active
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# Hardcode git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, `_invoke_fake_git`'s `"commit"` branch previously built its root-commit summary from a hardcoded f-string. When the `git_sandbox` fixture's file set changed, the fake's output silently drifted from real `git commit` output and `test_fake_git_matches_cassette[commit]` broke `ContractRefreshLoop`'s self-heal cycle. Fix: derive the summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time (file list + per-file insertion counts), so fake output stays in lockstep with fixture contents automatically.

**Why:** prevents this failure class from recurring every time someone edits the `git_sandbox` fixture.
