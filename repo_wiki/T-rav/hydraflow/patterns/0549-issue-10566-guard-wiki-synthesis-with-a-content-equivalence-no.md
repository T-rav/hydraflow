---
id: 0549
topic: patterns
source_issue: 10566
source_phase: plan
created_at: 2026-07-25T23:57:01.883149+00:00
status: superseded
corroborations: 1
superseded_by: 0550
---

# Guard wiki synthesis with a content-equivalence no-op check

`compile_topic_tracked` in `src/wiki_compiler.py` had no check for whether newly synthesized entries were substantively identical to the active set it's replacing — entry 0011 and its "replacement" 0017 were byte-identical, meaning `RepoWikiLoop` maintenance ticks were re-emitting the same knowledge under new ids every cycle. Add a content-equivalence guard before writing: if synthesized output matches active input content, skip the write and return 0 changes.

**Why:** without this guard, entry ids grow unboundedly on unchanged topics and every no-op refresh manufactures a fresh (and wrong) supersession edge.
