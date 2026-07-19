---
id: 0068
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.339338+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Filter evicted memories on both content prefix AND metadata status

Apply dual filters when loading recalled memories: check both the `[EVICTED]` content prefix and `status: evicted` in metadata before injecting into prompts.

Example: `if mem.content.startswith('[EVICTED]') or mem.metadata.get('status') == 'evicted': skip`.

**Why:** A single filter has a failure path; if one guard is missing or malformed, a tombstone leaks into agent prompts and produces confusing or incorrect agent behavior.
