---
id: 0037
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.318752+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Lazy-load memory context on explicit user action, not on list render

Fetch memory context only when the user expands a section — not when the HITL list view renders.

Example: expand button triggers `fetchMemoryContext(issueId)` — the list view fires no memory API calls.

**Why:** Pre-fetching on render causes N+1 API calls on every HITL list load, amplified by the number of open issues.
