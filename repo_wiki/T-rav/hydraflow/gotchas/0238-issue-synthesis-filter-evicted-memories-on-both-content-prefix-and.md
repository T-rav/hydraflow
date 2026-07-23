---
id: 0238
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.801683+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Filter evicted memories on both content prefix AND metadata status

Apply dual filters when loading recalled memories: check both the `[EVICTED]` content prefix and `status: evicted` in metadata before injecting into prompts.

Example: `if mem.content.startswith('[EVICTED]') or mem.metadata.get('status') == 'evicted': skip`.

**Why:** A single filter has a failure path; if one guard is missing or malformed, a tombstone leaks into agent prompts and produces confusing or incorrect agent behavior.
