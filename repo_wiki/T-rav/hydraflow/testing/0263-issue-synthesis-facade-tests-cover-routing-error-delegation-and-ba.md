---
id: 0263
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:12:03.093273+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Facade tests: cover routing, error, delegation, and backward compat

When testing a facade's `__getattr__`, verify four cases:
1. Correct method routes to the right sub-client.
2. Nonexistent method raises `AttributeError`.
3. Facade satisfies the protocol via delegation.
4. Existing tests that mock the original class still pass.

Assert sub-components receive mutable shared-state references, not copies.

**Why:** Missing any case allows silent routing failures to ship undetected.
