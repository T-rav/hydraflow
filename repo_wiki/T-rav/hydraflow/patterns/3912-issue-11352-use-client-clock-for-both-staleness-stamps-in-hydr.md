---
id: 3912
topic: patterns
source_issue: 11352
source_phase: plan
created_at: 2026-08-16T14:31:03.716384+00:00
status: active
corroborations: 1
---

# Use client clock for both staleness stamps in HydraFlowContext, never server time

Both `lastSnapshotAt` and `lastEventAt` must be stamped with the client clock at receipt time (`new Date()` in the reducer), matching the existing `pipelinePollerLastRun` idiom in the `pipeline_snapshot` case.

- WS event payloads carry server timestamps; using those for `lastEventAt` introduces clock-skew false trips on a healthy board.
- The pure predicate (`staleness.js`) receives both stamps already aligned to the same clock domain.

**Why:** Clock skew between server and client makes a healthy board look stale, flashing the resync chip during normal operation.
