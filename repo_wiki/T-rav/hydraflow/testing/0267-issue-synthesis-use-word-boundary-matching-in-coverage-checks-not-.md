---
id: 0267
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:34:51.013644+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Use word-boundary matching in coverage checks, not substring

When asserting that a name appears in coverage output, use full-name or word-boundary matching.

Example:
- Bad: `'Foo' in text` (matches `FooBar`)
- Good: `re.search(r'\bFoo\b', text)`

**Why:** Short-name collisions silently mark unrelated targets as covered, hiding real gaps in coverage.
