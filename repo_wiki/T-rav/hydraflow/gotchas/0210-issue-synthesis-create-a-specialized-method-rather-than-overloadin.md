---
id: 0210
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.160854+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Create a specialized method rather than overloading a general one

When a general method returns insufficient data for a specific use case, create a separate focused method rather than adding optional parameters.

Example: `list_issues_by_label()` returns basic metadata; `get_issue_updated_at()` handles timestamps in a separate call.

**Why:** Overloading general methods couples unrelated concerns and complicates callers that need only one piece of data.
