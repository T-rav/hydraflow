---
id: 0034
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.697057+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Filter evicted memories on both content prefix AND metadata status

Apply dual filters when loading recalled memories: check both the `[EVICTED]` content prefix and `status: evicted` in metadata before injecting into prompts.

Example: `if mem.content.startswith('[EVICTED]') or mem.metadata.get('status') == 'evicted': skip`.

**Why:** A single filter has a failure path; if one guard is missing or malformed, a tombstone leaks into agent prompts and produces confusing or incorrect agent behavior.
