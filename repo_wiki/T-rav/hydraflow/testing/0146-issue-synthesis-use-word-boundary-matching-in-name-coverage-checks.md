---
id: 0146
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.438696+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Use word-boundary matching in name-coverage checks to prevent collisions

Substring matching in coverage or name checks produces false positives when short names appear inside longer ones.

- Bad: `'Foo' in text` — also matches `FooBar`, `PrefixFoo`
- Good: `re.search(r'\bFoo\b', text)` or full-name match

**Why:** Short-name collisions silently mark unrelated targets as covered, hiding real gaps in coverage.
