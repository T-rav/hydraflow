---
id: 0306
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.882347+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Use word-boundary matching in coverage checks, not substring

When asserting that a name appears in coverage output, use full-name or word-boundary matching.

- Bad: `'Foo' in text` — also matches `FooBar`, `PrefixFoo`
- Good: `re.search(r'\bFoo\b', text)` or full-name match

**Why:** Short-name collisions silently mark unrelated targets as covered, hiding real gaps in coverage.
