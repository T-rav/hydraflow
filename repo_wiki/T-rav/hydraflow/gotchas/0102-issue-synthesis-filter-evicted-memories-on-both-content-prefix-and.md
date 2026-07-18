---
id: 0102
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.520172+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Filter evicted memories on both content prefix AND metadata status

Apply dual filters when loading recalled memories: check both the `[EVICTED]` content prefix and `status: evicted` in metadata before injecting into prompts.

Example: `if mem.content.startswith('[EVICTED]') or mem.metadata.get('status') == 'evicted': skip`.

**Why:** A single filter has a failure path; if one guard is missing or malformed, a tombstone leaks into agent prompts and produces confusing or incorrect agent behavior.
