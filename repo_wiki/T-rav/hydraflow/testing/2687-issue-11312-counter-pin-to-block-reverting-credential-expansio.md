---
id: 2687
topic: testing
source_issue: 11312
source_phase: plan
created_at: 2026-08-16T07:21:09.104042+00:00
status: active
corroborations: 1
---

# Counter-pin to block reverting credential expansions

When fixing env-isolation around provider keys, add a counter-pin asserting the original behaviour still holds under the ambient-key scenario the fix targets.

- Pin: `apply_repo_provider` returns `zai` when only `ZAI_CODING_PLAN_KEY` is set — blocks narrowing `_ZAI_API_KEY_ENVS` back to two names, which would silently revert #11267.
- Read env names through `credit_failover.zai_key_envs()`, never the private tuple.

**Why:** The obvious wrong fix (narrowing the env list) looks correct to a future maintainer but silently undoes a prior credential-coverage expansion.
