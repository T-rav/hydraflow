---
id: 1462
topic: testing
source_issue: 10798
source_phase: plan
created_at: 2026-07-28T10:05:46.407724+00:00
status: active
corroborations: 1
---

# `socket.sessions` array order is a merge artifact, not chronological

The `SESSIONS` case in `HydraFlowContext.jsx` builds `[...preserved, ...fetched]`, so a preserved-but-unfetched active session sits at index 0. Do not use `Array.find(s => s.status === 'active')` to pick "newest" — it returns the first match, not max-`started_at`. Filter to active, then delegate to `pickLatestSession` from `src/ui/src/utils/sessions.js`.

- Multiple sessions can be `active` at once (multi-repo `__all__` union; stale unclosed runs).
- `currentSessionId === null` makes the header clock from the wrong session.

**Why:** Index-0 order is an accident of the reducer merge, not a sorted guarantee; stale active runs produce wildly wrong uptime readouts.
