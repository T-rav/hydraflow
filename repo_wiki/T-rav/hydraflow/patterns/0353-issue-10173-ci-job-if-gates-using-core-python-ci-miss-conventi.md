---
id: 0353
topic: patterns
source_issue: 10173
source_phase: plan
created_at: 2026-07-22T16:50:02.909670+00:00
status: superseded
corroborations: 1
superseded_by: 0356
---

# CI job `if:` gates using core_python||ci miss convention-only PRs

A workflow job's `if:` referencing only `needs.changes.outputs.core_python == 'true' || needs.changes.outputs.ci == 'true'` skips entirely when a PR touches only `Makefile`, `.githooks/**`, or `scripts/hydraflow_audit/**` — none of those paths flip `core_python` or `ci` in the paths-filter step. Example: `.github/workflows/ci.yml` line 492, the `audit` job's `if:`. When adding a check whose source files live outside `src/`/`tests/`, add or extend a dedicated paths-filter output (e.g. a `conventions` filter) rather than assuming `core_python` covers it.

**Why:** Principles Audit silently not running on Makefile/hook/audit-script-only PRs defeats the audit's purpose for exactly the changes most likely to weaken it.
