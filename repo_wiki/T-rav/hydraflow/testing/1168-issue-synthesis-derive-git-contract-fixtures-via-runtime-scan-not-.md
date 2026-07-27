---
id: 1168
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.848734+00:00
status: superseded
corroborations: 1
supersedes: 1099
superseded_by: 1242
---

# Derive git contract fixtures via runtime scan, not literals

In tests/trust/contracts/test_fake_git_contract.py, build _invoke_fake_git's commit summary from a helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from git_sandbox at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** A hardcoded summary silently drifted from real git commit output whenever the git_sandbox fixture's file set changed, breaking test_fake_git_matches_cassette[commit] and ContractRefreshLoop's self-heal cycle.
