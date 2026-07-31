---
id: 1940
topic: testing
source_issue: 10878
source_phase: plan
created_at: 2026-07-31T07:10:49.839299+00:00
status: superseded
corroborations: 1
superseded_by: 2065
---

# setup_branch_protection.py --apply strips undeclared live-required contexts

Never run `setup_branch_protection.py --apply` to resolve drift where a live-required context is missing from `gates.toml`. The command PUTs the canonical payload verbatim, silently de-requiring any live gate that has no `[[gate]]` record.

Example: `CI Gate` was required on `staging` live (harm fix from #10672) but undeclared in `gates.toml`. Running `--apply` would strip it from live, reopening the red-PR-into-staging harm.

**Why:** `--apply` is lossy when the contract is incomplete — it cannot distinguish "should not be required" from "was never declared."

Use the P1 regression pin `test_applying_canonical_would_not_strip_ci_gate_from_live` to guard against this class of mistake.
