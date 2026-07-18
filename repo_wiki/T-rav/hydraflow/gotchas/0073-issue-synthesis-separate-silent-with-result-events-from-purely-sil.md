---
id: 0073
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.909545+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Separate silent-with-result events from purely silent events in dispatch dicts

In event dispatch tables, distinguish events that produce no display output but set a result value (e.g., `agent_end`, `turn_end`) from events that are truly silent and set nothing.

Example: check `_SILENT_WITH_RESULT` before `_SILENT_EVENTS` so result-setting events are routed correctly.

**Why:** Treating silent-with-result events as purely silent discards their return values, causing downstream state to silently receive `None` instead of the real result.
