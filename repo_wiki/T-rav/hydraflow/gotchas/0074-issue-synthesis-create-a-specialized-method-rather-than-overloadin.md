---
id: 0074
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.909727+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Create a specialized method rather than overloading a general one

When a general method returns insufficient data for a specific use case, create a separate focused method rather than adding optional parameters.

Example: `list_issues_by_label()` returns basic metadata; `get_issue_updated_at()` handles timestamps in a separate call — not an optional flag on the list method.

**Why:** Overloading general methods couples unrelated concerns and complicates callers that need only one piece of data.
