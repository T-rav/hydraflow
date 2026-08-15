---
id: 2450
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:23.148528+00:00
status: superseded
corroborations: 1
supersedes: 2330
superseded_by: 2573
---

# Guard wiki synthesis with a content-equivalence no-op check

`compile_topic_tracked` in `src/wiki_compiler.py` must check whether newly synthesized entries are substantively identical to the active set before writing — if content matches, skip the write and return 0 changes.

Example: Entry 0011 and its "replacement" 0017 were byte-identical, meaning `RepoWikiLoop` maintenance ticks re-emitted the same knowledge under new ids every cycle. See also: [patterns] — No-op synthesis guard must partition per-entry with multiset matching.

**Why:** Without this guard, entry ids grow unboundedly on unchanged topics and every no-op refresh manufactures a fresh (and wrong) supersession edge.
