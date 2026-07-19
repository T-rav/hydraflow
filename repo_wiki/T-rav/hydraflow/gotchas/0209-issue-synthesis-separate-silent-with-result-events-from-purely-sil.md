---
id: 0209
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.160452+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Separate silent-with-result events from purely silent in dispatch

In event dispatch tables, distinguish events that produce no display output but set a result value from events that are truly silent.

Example: check `_SILENT_WITH_RESULT` before `_SILENT_EVENTS` so result-setting events are routed correctly.

**Why:** Treating silent-with-result events as purely silent discards their return values, causing downstream state to silently receive `None` instead of the real result.
