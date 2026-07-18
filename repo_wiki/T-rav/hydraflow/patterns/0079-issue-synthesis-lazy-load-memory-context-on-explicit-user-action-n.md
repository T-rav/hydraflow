---
id: 0079
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.535318+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Lazy-load memory context on explicit user action, not on list render

Fetch memory context only when the user expands a section — not when the HITL list view renders.

Example: expand button triggers `fetchMemoryContext(issueId)` — the list view fires no memory API calls.

**Why:** Pre-fetching on render causes N+1 API calls on every HITL list load, amplified by the number of open issues.
