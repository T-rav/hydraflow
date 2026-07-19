---
id: 0107
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.521339+00:00
status: superseded
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
superseded_by: 0112
---

# Separate silent-with-result events from purely silent in dispatch

In event dispatch tables, distinguish events that produce no display output but set a result value (e.g., `agent_end`, `turn_end`) from events that are truly silent and set nothing.

Example: check `_SILENT_WITH_RESULT` before `_SILENT_EVENTS` so result-setting events are routed correctly.

**Why:** Treating silent-with-result events as purely silent discards their return values, causing downstream state to silently receive `None` instead of the real result.
