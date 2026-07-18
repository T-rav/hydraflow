---
id: 0293
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.503591+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Test Pydantic Literal constraints: cover both valid and invalid values

When adding `Literal` constraints to Pydantic fields, test both valid and invalid values — verify valid values are accepted and invalid values raise `ValidationError`.

Example: For `status: Literal['open', 'closed']`, test `status='open'` passes and `status='unknown'` raises.

**Why:** Literal constraints are invisible at runtime if only valid values are tested; invalid-value tests confirm the constraint is actually enforced.
