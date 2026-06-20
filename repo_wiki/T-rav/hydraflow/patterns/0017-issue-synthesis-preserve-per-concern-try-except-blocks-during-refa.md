---
id: 0017
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.314606+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Preserve per-concern try/except blocks during refactoring

Do not merge or widen separate try/except blocks that each guard a specific concern — keep them as-is when extracting surrounding code.

Example: if `fetch_labels()` and `post_comment()` each have their own try/except, extracted helpers must not share a single outer handler.

**Why:** Merging exception scopes lets a failure in one concern silently suppress or skip a different concern.
