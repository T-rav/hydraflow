---
id: 0215
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.794015+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Test Pydantic Literal constraints: cover both valid and invalid values

When adding `Literal` constraints to Pydantic fields, test both valid and invalid values — verify valid values are accepted and invalid values raise `ValidationError`.

Example: For `status: Literal['open', 'closed']`, test `status='open'` passes and `status='unknown'` raises.

**Why:** Literal constraints are invisible at runtime if only valid values are tested; invalid-value tests confirm the constraint is actually enforced.
