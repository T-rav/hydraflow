---
id: 0607
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.352360+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Guard wiki synthesis with a content-equivalence no-op check

`compile_topic_tracked` in `src/wiki_compiler.py` must check whether newly synthesized entries are substantively identical to the active set it's replacing before writing. If synthesized output matches active input content, skip the write and return 0 changes.

Example: entry 0011 and its "replacement" 0017 were byte-identical, re-emitting the same knowledge under new ids every cycle.

**Why:** without this guard, entry ids grow unboundedly on unchanged topics and every no-op refresh manufactures a fresh (wrong) supersession edge.
