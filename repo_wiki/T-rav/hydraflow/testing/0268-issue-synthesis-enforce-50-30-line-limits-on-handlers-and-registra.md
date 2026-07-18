---
id: 0268
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.485534+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Enforce 50/30-line limits on handlers and registration wiring

Keep handler functions to ≤ 50 lines and registration wiring to ≤ 30 lines. Extract nested closures into instance methods to hold nesting to ≤ 3 levels.

Enforce via AST-based tests with ±3 line tolerance. See also: testing — Allow ±3 line drift in AST-based structure assertions.

**Why:** Functions exceeding these limits are difficult to test in isolation; deeply nested closures cannot be mocked independently.
