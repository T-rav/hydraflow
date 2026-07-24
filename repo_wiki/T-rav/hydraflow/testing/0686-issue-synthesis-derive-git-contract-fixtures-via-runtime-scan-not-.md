---
id: 0686
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.852457+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# Derive git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, build `_invoke_fake_git`'s `"commit"` branch root-commit summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from `git_sandbox` at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** a hardcoded summary silently drifted from real `git commit` output whenever the `git_sandbox` fixture's file set changed, breaking `test_fake_git_matches_cassette[commit]` and `ContractRefreshLoop`'s self-heal cycle.
