---
id: 0577
topic: patterns
source_issue: 10592
source_phase: plan
created_at: 2026-07-26T03:33:58.716400+00:00
status: active
corroborations: 1
---

# HydraFlowContext.jsx stores orchestratorStatus verbatim — default unknowns, don't enum

`HydraFlowContext.jsx:172-194`'s reducer stores the server's `orchestratorStatus` string as-is, with no client-side validation. Any UI deriving style/state from it must use a state→style map with a `default` fallback branch, not an exhaustive `idle`/`done` enum — an unrecognized string must degrade gracefully (e.g. to an "off" style) rather than resolve to `undefined`.

**Why:** the client doesn't control the vocabulary of values the server can send, so exhaustive enums silently break on any new/renamed backend status string.
