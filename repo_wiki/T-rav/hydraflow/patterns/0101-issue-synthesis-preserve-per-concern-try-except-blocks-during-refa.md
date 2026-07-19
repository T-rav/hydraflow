---
id: 0101
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.960176+00:00
status: superseded
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
superseded_by: 0134
---

# Preserve per-concern try/except blocks during refactoring

Do not merge or widen separate try/except blocks that each guard a specific concern — keep them as-is when extracting surrounding code.

Example: if `fetch_labels()` and `post_comment()` each have their own try/except, extracted helpers must not share a single outer handler.

**Why:** Merging exception scopes lets a failure in one concern silently suppress or skip a different concern.
