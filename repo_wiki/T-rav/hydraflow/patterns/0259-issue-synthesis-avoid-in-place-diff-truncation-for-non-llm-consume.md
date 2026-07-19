---
id: 0259
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.232977+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Avoid in-place diff truncation for non-LLM consumers

When a diff is truncated for an LLM prompt, rebind to a separate name rather than mutating the original variable.

Example: `prompt_diff = diff[:max_diff] + "[truncated]"` instead of reassigning `diff`, so the full `diff` is still available for structural consumers.

**Why:** In-place truncation causes coverage mapping to silently under-report changed lines in the tail of large diffs, making the gate fail-open on the diffs most likely to need it.
