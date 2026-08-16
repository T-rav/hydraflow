---
id: 3756
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.667707+00:00
status: superseded
corroborations: 1
supersedes: 3611
superseded_by: 3901
---

# RC promotion PRs collapse merge-base range on main (ADR-0042)

When an RC-promotion PR targets `main` but the branch is cut from `staging`'s tip (per ADR-0042), `merge_base(origin/main, HEAD)..HEAD` collapses to near-empty — every promoted commit goes unscanned. Always supply `HYDRAFLOW_AUDIT_PR_BASE` from `github.base_ref` so `scripts/check_console_conformance.py` scans the correct range. In `ci.yml`'s `audit` job, hoist `HYDRAFLOW_AUDIT_PR_BASE: ${{ github.base_ref }}` to a job-level `env:` block.

**Why:** Without the PR-base hint, `_resolve_merge_base` falls through to the `origin/staging` fallback, which is the branch the RC was cut *from* — yielding an empty diff.
