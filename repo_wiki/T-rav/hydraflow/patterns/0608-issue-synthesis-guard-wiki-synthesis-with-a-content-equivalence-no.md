---
id: 0608
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:31:18.170793+00:00
status: superseded
corroborations: 1
supersedes: 0574
superseded_by: 0650
---

# Guard wiki synthesis with a content-equivalence no-op check

`compile_topic_tracked` in `src/wiki_compiler.py` must check whether newly synthesized entries are substantively identical to the active set before writing — if content matches, skip the write and return 0 changes.

Example: Entry 0011 and its "replacement" 0017 were byte-identical, meaning `RepoWikiLoop` maintenance ticks re-emitted the same knowledge under new ids every cycle.

**Why:** Without this guard, entry ids grow unboundedly on unchanged topics and every no-op refresh manufactures a fresh (and wrong) supersession edge.
