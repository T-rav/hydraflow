---
id: 3092
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:41:05.440650+00:00
status: active
corroborations: 1
supersedes: 2958
---

# Use red-first precedence tests for credential refactors

Write precedence-parity tests capturing existing behavior before moving call sites to `SecretsProviderPort`.

Example: Test that `build_credentials` returns identical `gh_token` values for env-var, `.env`, and both-set cases. See also: [patterns] — Maintain single dotenv parser and env key allowlist.

**Why:** Subtle changes in empty-string vs missing key handling can cause a blank `GH_TOKEN`, resulting in silent auth failures mid-run.
