---
id: 0581
topic: testing
source_issue: 10230
source_phase: plan
created_at: 2026-07-22T18:13:39.968020+00:00
status: active
corroborations: 1
---

# Hardcode git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, `_invoke_fake_git`'s `"commit"` branch previously built its root-commit summary from a hardcoded f-string. When the `git_sandbox` fixture's file set changed, the fake's output silently drifted from real `git commit` output and `test_fake_git_matches_cassette[commit]` broke `ContractRefreshLoop`'s self-heal cycle. Fix: derive the summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time (file list + per-file insertion counts), so fake output stays in lockstep with fixture contents automatically.

**Why:** prevents this failure class from recurring every time someone edits the `git_sandbox` fixture.
