---
id: 0143
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.023559+00:00
status: superseded
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
superseded_by: 0176
---

# Preserve per-concern try/except blocks during refactoring

Do not merge or widen separate try/except blocks that each guard a specific concern — keep them as-is when extracting surrounding code.

Example: if `fetch_labels()` and `post_comment()` each have their own try/except, extracted helpers must not share a single outer handler.

**Why:** Merging exception scopes lets a failure in one concern silently suppress or skip a different concern.
