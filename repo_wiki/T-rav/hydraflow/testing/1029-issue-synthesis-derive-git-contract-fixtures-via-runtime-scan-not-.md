---
id: 1029
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.457561+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Derive git contract fixtures via runtime scan, not literal strings

In tests/trust/contracts/test_fake_git_contract.py, build _invoke_fake_git's "commit" branch root-commit summary from a _root_commit_summary() helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from git_sandbox at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** a hardcoded summary silently drifted from real git commit output whenever the git_sandbox fixture's file set changed, breaking test_fake_git_matches_cassette[commit] and ContractRefreshLoop's self-heal cycle.
