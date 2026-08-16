---
id: 3328
topic: patterns
source_issue: 11222
source_phase: plan
created_at: 2026-08-16T05:46:03.674980+00:00
status: superseded
corroborations: 1
superseded_by: 3464
---

# RC promotion PRs collapse merge-base range on main (ADR-0042)

When an RC-promotion PR targets `main` but the branch is cut from `staging`'s tip (per ADR-0042), `merge_base(origin/main, HEAD)..HEAD` collapses to near-empty — every promoted commit goes unscanned. Always supply `HYDRAFLOW_AUDIT_PR_BASE` from `github.base_ref` so `scripts/check_console_conformance.py` scans the correct range. In `ci.yml`'s `audit` job, hoist `HYDRAFLOW_AUDIT_PR_BASE: ${{ github.base_ref }}` to a job-level `env:` block so both the `make audit` and `make console-conformance` steps inherit it. **Why:** without the PR-base hint, `_resolve_merge_base` falls through to the `origin/staging` fallback, which is the branch the RC was cut *from* — yielding an empty diff.
