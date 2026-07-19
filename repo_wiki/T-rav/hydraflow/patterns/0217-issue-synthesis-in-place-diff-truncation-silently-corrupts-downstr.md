---
id: 0217
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.642864+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# In-place diff truncation silently corrupts downstream non-LLM consumers

When a diff is truncated for an LLM prompt, rebind to a separate name rather than mutating the original variable.

Example: `prompt_diff = diff[:max_diff] + "[truncated]"` instead of reassigning `diff`, so the full `diff` is still available for structural consumers.

**Why:** In-place truncation causes coverage mapping to silently under-report changed lines in the tail of large diffs, making the gate fail-open on the diffs most likely to need it.
