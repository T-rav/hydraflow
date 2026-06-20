---
id: 0180
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.583171+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Existing tests cover private-method extractions; add only new-behavior tests

When extracting a private method from a public one with an unchanged public API, the existing test suite provides full coverage — no new tests needed for the extraction itself. When extracting prompt-building methods, run prompt-assertion tests in isolation immediately after extraction to verify parity.

**Why:** Adding duplicate tests for unchanged behavior inflates the suite; the real regression risk is behavioral, which existing tests already guard.
