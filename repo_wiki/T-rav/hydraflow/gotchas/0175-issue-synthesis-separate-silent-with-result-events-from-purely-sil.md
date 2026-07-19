---
id: 0175
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.956294+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Separate silent-with-result events from purely silent in dispatch

In event dispatch tables, distinguish events that produce no display output but set a result value from events that are truly silent.

Example: check `_SILENT_WITH_RESULT` before `_SILENT_EVENTS` so result-setting events are routed correctly.

**Why:** Treating silent-with-result events as purely silent discards their return values, causing downstream state to silently receive `None` instead of the real result.
