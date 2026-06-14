---
id: 0039
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.698054+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Separate silent-with-result events from purely silent events in dispatch dicts

In event dispatch tables, distinguish events that produce no display output but set a result value (e.g., `agent_end`, `turn_end`) from events that are truly silent and set nothing.

Example: check `_SILENT_WITH_RESULT` before `_SILENT_EVENTS` so result-setting events are routed correctly.

**Why:** Treating silent-with-result events as purely silent discards their return values, causing downstream state to silently receive `None` instead of the real result.
