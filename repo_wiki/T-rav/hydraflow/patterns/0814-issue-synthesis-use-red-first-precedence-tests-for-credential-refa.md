---
id: 0814
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T12:54:49.517438+00:00
status: active
corroborations: 1
supersedes: 0758
---

# Use red-first precedence tests for credential refactors

Write precedence-parity tests capturing existing behavior before moving call sites to `SecretsProviderPort`.

Example: Test that `build_credentials` returns identical `gh_token` values for env-var, `.env`, and both-set cases.

**Why:** Subtle changes in empty-string vs missing key handling can cause a blank `GH_TOKEN`, resulting in silent auth failures mid-run.
