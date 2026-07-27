---
id: 0574
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.790412+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0608
---

# Guard wiki synthesis with a content-equivalence no-op check

`compile_topic_tracked` in `src/wiki_compiler.py` had no check for whether newly synthesized entries were substantively identical to the active set it's replacing — entry 0011 and its "replacement" 0017 were byte-identical, meaning `RepoWikiLoop` maintenance ticks were re-emitting the same knowledge under new ids every cycle. Add a content-equivalence guard before writing: if synthesized output matches active input content, skip the write and return 0 changes.

**Why:** without this guard, entry ids grow unboundedly on unchanged topics and every no-op refresh manufactures a fresh (and wrong) supersession edge.
