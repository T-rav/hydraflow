---
id: 1552
topic: gotchas
source_issue: 11963
source_phase: plan
created_at: 2026-09-01T09:53:18.676610+00:00
status: active
corroborations: 1
---

# Guard order in MemoryBacklogLoop: dedup → query → attempts → create

In `MemoryBacklogLoop` ticks, the guard sequence must be dedup-check → durable `PRPort.list_issues_by_label` query → `inc_memory_backlog_attempts` → `create_issue`. Never increment attempts before the durable guard runs.

- A guard-skip on an open citing issue must NOT call `inc_memory_backlog_attempts`.
- Wrong order manufactures false 3-strikes HITL escalations for issues that are already open.

**Why:** Incrementing before the guard would push legitimately-open entries toward re-filing escalation, defeating the dedup guard's purpose.
