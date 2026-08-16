---
id: 2682
topic: testing
source_issue: 11311
source_phase: plan
created_at: 2026-08-16T07:14:25.767548+00:00
status: active
corroborations: 1
---

# Pin cross-module list parity with a registry-sync test

When two independently-maintained lists must enumerate the same set, add a test asserting equality so a future addition can't drift them apart.

- `tests/test_credit_failover.py`: assert the keys `credit_failover` accepts equal those the z.ai harness backend authenticates with.
- Without this pin, `credit_failover._ZAI_API_KEY_ENVS` and the harness `api_key_envs` can silently diverge.

**Why:** A fifth key added to one list but not the other would either break failover or break ADR conformance with no visible signal.
