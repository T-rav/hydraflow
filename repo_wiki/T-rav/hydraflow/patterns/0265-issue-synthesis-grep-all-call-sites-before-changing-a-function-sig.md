---
id: 0265
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.709465+00:00
status: active
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
---

# Grep all call sites before changing a function signature

Run `git grep <function_name>` before modifying any signature; for public functions, verify zero remaining unpatched matches after the change.

Example: `git grep 'load_state'` before changing its return type — update every caller in the same commit.

**Why:** Missing even one call site causes `TypeError` at runtime; exhaustive grep audit is the only way to confirm full coverage.
