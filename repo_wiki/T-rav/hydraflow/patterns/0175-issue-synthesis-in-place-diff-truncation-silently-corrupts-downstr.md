---
id: 0175
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.033282+00:00
status: superseded
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
superseded_by: 0176
---

# In-place diff truncation silently corrupts downstream non-LLM consumers

When a diff is truncated for an LLM prompt, rebind to a separate name rather than mutating the original variable.

Example: `prompt_diff = diff[:max_diff] + "[truncated]"` instead of reassigning `diff`, so the full `diff` is still available for structural consumers.

**Why:** In-place truncation causes coverage mapping to silently under-report changed lines in the tail of large diffs, making the gate fail-open on the diffs most likely to need it.
