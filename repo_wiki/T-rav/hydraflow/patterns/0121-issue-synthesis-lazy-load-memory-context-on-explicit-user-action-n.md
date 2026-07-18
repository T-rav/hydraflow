---
id: 0121
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.964787+00:00
status: superseded
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
superseded_by: 0134
---

# Lazy-load memory context on explicit user action, not on list render

Fetch memory context only when the user expands a section — not when the HITL list view renders.

Example: expand button triggers `fetchMemoryContext(issueId)` — the list view fires no memory API calls.

**Why:** Pre-fetching on render causes N+1 API calls on every HITL list load, amplified by the number of open issues.
