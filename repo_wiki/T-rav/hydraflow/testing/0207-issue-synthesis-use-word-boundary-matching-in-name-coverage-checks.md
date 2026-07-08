---
id: 0207
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.791102+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Use word-boundary matching in name-coverage checks to prevent collisions

Substring matching in coverage or name checks produces false positives when short names appear inside longer ones.

- Bad: `'Foo' in text` — also matches `FooBar`, `PrefixFoo`
- Good: `re.search(r'\bFoo\b', text)` or full-name match

**Why:** Short-name collisions silently mark unrelated targets as covered, hiding real gaps in coverage.
