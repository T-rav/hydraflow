---
id: 0247
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.228135+00:00
status: superseded
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
superseded_by: 0260
---

# Lazy-load memory context on explicit user action

Fetch memory context only when the user expands a section — not when the HITL list view renders.

Example: Expand button triggers `fetchMemoryContext(issueId)` — the list view fires no memory API calls.

**Why:** Pre-fetching on render causes N+1 API calls on every HITL list load, amplified by the number of open issues.
