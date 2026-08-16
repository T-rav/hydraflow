---
id: 2664
topic: testing
source_issue: 11295
source_phase: plan
created_at: 2026-08-16T02:40:08.127265+00:00
status: active
corroborations: 1
---

# SESSIONS reducer prepends preserved actives; array index 0 may be stale

The `SESSIONS` reducer at `HydraFlowContext.jsx:832` *prepends* preserved active sessions. Combined with `currentSessionId` being nulled on completion (`:824`), `list.find(s => s?.status === 'active')` at `vitals.js:163` returns the stale session at index 0, not the newest.

When selecting among active sessions, filter `status === 'active'` then reduce by greatest parseable `started_at` — do not assume array order reflects recency.

**Why:** Reducer prepend semantics break the assumption that first-active equals newest-active, causing wrong "factory RUNTIME" in `ConsoleHeader`.
