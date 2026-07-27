---
id: 0583
topic: patterns
source_issue: 10613
source_phase: plan
created_at: 2026-07-26T10:32:19.699679+00:00
status: superseded
corroborations: 1
superseded_by: 0614
---

# Use red-first precedence tests for credential refactors

Write precedence-parity tests capturing existing behavior before moving call sites to `SecretsProviderPort`. Test that `build_credentials` returns identical `gh_token` values for env-var, `.env`, and both-set cases.
**Why:** Subtle changes in empty-string vs missing key handling can cause a blank `GH_TOKEN`, resulting in silent auth failures mid-run.
