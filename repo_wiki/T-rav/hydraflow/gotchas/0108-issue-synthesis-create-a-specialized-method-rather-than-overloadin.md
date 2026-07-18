---
id: 0108
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.489497+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Create a specialized method rather than overloading a general one

When a general method returns insufficient data for a specific use case, create a separate focused method rather than adding optional parameters.

Example: `list_issues_by_label()` returns basic metadata; `get_issue_updated_at()` handles timestamps in a separate call — not an optional flag on the list method.

**Why:** Overloading general methods couples unrelated concerns and complicates callers that need only one piece of data.
