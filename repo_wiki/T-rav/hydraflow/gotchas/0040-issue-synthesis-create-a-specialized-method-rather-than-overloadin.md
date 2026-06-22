---
id: 0040
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.698248+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Create a specialized method rather than overloading a general one

When a general method returns insufficient data for a specific use case, create a separate focused method rather than adding optional parameters.

Example: `list_issues_by_label()` returns basic metadata; `get_issue_updated_at()` handles timestamps in a separate call — not an optional flag on the list method.

**Why:** Overloading general methods couples unrelated concerns and complicates callers that need only one piece of data.
