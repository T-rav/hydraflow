---
id: 0176
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.956600+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Create a specialized method rather than overloading a general one

When a general method returns insufficient data for a specific use case, create a separate focused method rather than adding optional parameters.

Example: `list_issues_by_label()` returns basic metadata; `get_issue_updated_at()` handles timestamps in a separate call.

**Why:** Overloading general methods couples unrelated concerns and complicates callers that need only one piece of data.
