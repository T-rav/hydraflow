---
id: 0211
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.792497+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Existing tests cover private-method extractions; add only new-behavior tests

When extracting a private method from a public one with an unchanged public API, the existing test suite provides full coverage — no new tests are needed for the extraction itself. When extracting prompt-building methods, run prompt-assertion tests in isolation immediately after extraction to verify parity.

**Why:** Adding duplicate tests for unchanged behavior inflates the suite; the real regression risk is behavioral, which existing tests already guard.
