---
id: 1682
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:30.371655+00:00
status: superseded
corroborations: 1
supersedes: 1588
superseded_by: 1778
---

# Use red-first precedence tests for credential refactors

Write precedence-parity tests capturing existing behavior before moving call sites to `SecretsProviderPort`.

Example: Test that `build_credentials` returns identical `gh_token` values for env-var, `.env`, and both-set cases.

**Why:** Subtle changes in empty-string vs missing key handling can cause a blank `GH_TOKEN`, resulting in silent auth failures mid-run.
