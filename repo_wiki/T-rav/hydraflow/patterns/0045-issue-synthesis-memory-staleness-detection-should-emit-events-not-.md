---
id: 0045
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.320763+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Memory staleness detection should emit events, not silently mutate state

Staleness detection must emit events or log warnings rather than silently deleting or modifying stale entries.

Example: `event_bus.publish(STALE_MEMORY, item_id=item.id, age_days=age)` instead of `self._items.pop(item.id)`.

**Why:** Silent mutation removes the operator's ability to review or override staleness decisions; events keep the action reversible.
