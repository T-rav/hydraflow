---
id: 2665
topic: testing
source_issue: 11295
source_phase: plan
created_at: 2026-08-16T02:40:08.127281+00:00
status: active
corroborations: 1
---

# pickLatestSession lacks status filter; don't generalize for active-only selection

`pickLatestSession` at `SessionSidebar.jsx:9` selects the newest session but has no `status === 'active'` filter. Reusing it for `factoryStartMs` selection would report a completed run's start time.

Instead, implement the filtered selection inline at the call site in `vitals.js` and record the divergence from `pickLatestSession` in a comment. Generalizing `pickLatestSession` to accept a status filter is out-of-scope blast radius.

**Why:** A completed session with a later `started_at` would beat a live active session, producing a stale runtime value.
