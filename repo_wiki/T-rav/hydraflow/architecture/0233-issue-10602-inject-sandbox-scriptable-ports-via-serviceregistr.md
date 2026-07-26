---
id: 0233
topic: architecture
source_issue: 10602
source_phase: plan
created_at: 2026-07-26T10:26:40.201322+00:00
status: active
corroborations: 1
---

# Inject sandbox scriptable ports via ServiceRegistry

Inject sandbox scriptable overrides via a `Port` on `ServiceRegistry`. For example, `build_services(provider_canary=None)` constructs the real canary, but sandbox scenarios can pass a `ProviderCanaryPort` fake to script verdicts and auto-resume paused factories. **Why:** Prevents sandbox tests from hanging when the real Claude canary returns UNKNOWN in an air-gapped environment.
