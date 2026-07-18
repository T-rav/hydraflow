---
id: 0291
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.502113+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Existing tests cover private-method extractions; add only new-behavior tests

When extracting a private method from a public one with an unchanged public API, the existing test suite provides full coverage — no new tests are needed for the extraction itself.

When extracting prompt-building methods, run prompt-assertion tests in isolation immediately after extraction to verify parity.

**Why:** Adding duplicate tests for unchanged behavior inflates the suite; the real regression risk is behavioral, which existing tests already guard.
