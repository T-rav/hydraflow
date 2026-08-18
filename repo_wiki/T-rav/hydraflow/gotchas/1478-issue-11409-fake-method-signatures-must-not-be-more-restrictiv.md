---
id: 1478
topic: gotchas
source_issue: 11409
source_phase: plan
created_at: 2026-08-18T03:04:36.397104+00:00
status: active
corroborations: 1
---

# Fake method signatures must not be more restrictive than reference

Rule: A parameter that is `POSITIONAL_OR_KEYWORD` on the reference class must not be `KEYWORD_ONLY` on the Fake — fake-more-permissive stays legal. Extend `_signatures_compatible` in `tests/test_mockworld_fakes_conformance.py` to enforce this.

Example: `FakeWikiCompiler.compile_topic_tracked` had a stray `*` making it keyword-only, but `src/repo_wiki_loop.py` called it positionally — crashing the tick.

**Why:** A positional call against a keyword-only fake param raises `TypeError`, which is in `LIKELY_BUG_EXCEPTIONS` and aborts the entire tick instead of degrading.
