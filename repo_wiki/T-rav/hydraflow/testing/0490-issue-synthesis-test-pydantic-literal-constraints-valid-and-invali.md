---
id: 0490
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.385531+00:00
status: active
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
---

# Test Pydantic Literal constraints: valid and invalid

When adding `Literal` constraints to Pydantic fields, test both valid and invalid values — verify valid values are accepted and invalid values raise `ValidationError`.

Example: For `status: Literal['open', 'closed']`, test `status='open'` passes and `status='unknown'` raises.

**Why:** Literal constraints are invisible at runtime if only valid values are tested; invalid-value tests confirm the constraint is actually enforced.
