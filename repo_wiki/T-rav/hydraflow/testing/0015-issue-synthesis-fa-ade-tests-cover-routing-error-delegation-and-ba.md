---
id: 0015
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409248+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Façade tests: cover routing, error, delegation, and backward compat

When testing a façade's `__getattr__`, verify four cases:
1. Correct method routes to the right sub-client.
2. Nonexistent method raises `AttributeError`.
3. Façade satisfies the protocol via delegation.
4. Existing tests that mock the original class still pass.

Verify sub-components receive mutable shared-state references, not copies.

**Why:** Missing any case allows silent routing failures to ship undetected.
