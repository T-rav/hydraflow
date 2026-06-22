---
id: 0116
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.086241+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Use word-boundary matching in name-coverage checks to prevent collisions

Substring matching in coverage or name checks produces false positives when short names appear inside longer ones.

- Bad: `'Foo' in text` — also matches `FooBar`, `PrefixFoo`
- Good: `re.search(r'\bFoo\b', text)` or full-name match

**Why:** Short-name collisions silently mark unrelated targets as covered, hiding real gaps in coverage.
