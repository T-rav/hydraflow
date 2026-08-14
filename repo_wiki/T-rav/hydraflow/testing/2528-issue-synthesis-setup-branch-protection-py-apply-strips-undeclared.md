---
id: 2528
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.957741+00:00
status: active
corroborations: 1
supersedes: 2339
---

# setup_branch_protection.py --apply strips undeclared live contexts

Never run `setup_branch_protection.py --apply` to resolve drift where a live-required context is missing from `gates.toml`. The command PUTs the canonical payload verbatim, silently de-requiring any live gate that has no `[[gate]]` record.

Example: `CI Gate` was required on `staging` live (harm fix from #10672) but undeclared in `gates.toml`. Running `--apply` would strip it from live, reopening the red-PR-into-staging harm. Use the P1 regression pin `test_applying_canonical_would_not_strip_ci_gate_from_live`.

**Why:** `--apply` is lossy when the contract is incomplete — it cannot distinguish 'should not be required' from 'was never declared.'
