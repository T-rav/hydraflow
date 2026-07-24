---
id: 0861
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.428023+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# Derive git contract fixtures via runtime scan, not literal strings

In `tests/trust/contracts/test_fake_git_contract.py`, build `_invoke_fake_git`'s `"commit"` branch root-commit summary from a `_root_commit_summary()` helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from `git_sandbox` at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** a hardcoded summary silently drifted from real `git commit` output whenever the `git_sandbox` fixture's file set changed, breaking `test_fake_git_matches_cassette[commit]` and `ContractRefreshLoop`'s self-heal cycle.
