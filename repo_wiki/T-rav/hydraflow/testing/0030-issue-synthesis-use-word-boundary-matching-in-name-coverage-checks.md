---
id: 0030
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.831241+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Use word-boundary matching in name-coverage checks to prevent collisions

Substring matching in coverage or name checks produces false positives when short names appear inside longer ones.

- Bad: `"Foo" in text` — also matches `FooBar`, `PrefixFoo`
- Good: `re.search(r'\bFoo\b', text)` or full-name match

**Why:** Short-name collisions silently mark unrelated targets as covered, hiding real gaps in coverage.
