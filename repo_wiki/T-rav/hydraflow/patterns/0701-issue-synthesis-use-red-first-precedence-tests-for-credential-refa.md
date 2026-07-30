---
id: 0701
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:37:52.933579+00:00
status: superseded
corroborations: 1
supersedes: 0656
superseded_by: 0758
---

# Use red-first precedence tests for credential refactors

Write precedence-parity tests capturing existing behavior before moving call sites to `SecretsProviderPort`.

Example: Test that `build_credentials` returns identical `gh_token` values for env-var, `.env`, and both-set cases.

**Why:** Subtle changes in empty-string vs missing key handling can cause a blank `GH_TOKEN`, resulting in silent auth failures mid-run.
