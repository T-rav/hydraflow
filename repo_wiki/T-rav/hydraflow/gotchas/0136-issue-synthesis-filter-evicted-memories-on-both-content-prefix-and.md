---
id: 0136
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.605110+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Filter evicted memories on both content prefix AND metadata status

Apply dual filters when loading recalled memories: check both the `[EVICTED]` content prefix and `status: evicted` in metadata before injecting into prompts.

Example: `if mem.content.startswith('[EVICTED]') or mem.metadata.get('status') == 'evicted': skip`.

**Why:** A single filter has a failure path; if one guard is missing or malformed, a tombstone leaks into agent prompts and produces confusing or incorrect agent behavior.
