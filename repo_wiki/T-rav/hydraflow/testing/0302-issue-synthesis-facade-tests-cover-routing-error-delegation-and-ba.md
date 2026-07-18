---
id: 0302
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.880237+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Facade tests: cover routing, error, delegation, and backward compat

When testing a facade's `__getattr__`, verify four cases:
1. Correct method routes to the right sub-client.
2. Nonexistent method raises `AttributeError`.
3. Facade satisfies the protocol via delegation.
4. Existing tests that mock the original class still pass.

Assert sub-components receive mutable shared-state references, not copies.

**Why:** Missing any case allows silent routing failures to ship undetected.
