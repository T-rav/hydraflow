---
id: 0255
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.231306+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Memory staleness detection must emit events, not mutate state

Staleness detection must emit events or log warnings rather than silently deleting or modifying stale entries.

Example: `event_bus.publish(STALE_MEMORY, item_id=item.id, age_days=age)` instead of `self._items.pop(item.id)`.

**Why:** Silent mutation removes the operator's ability to review or override staleness decisions; events keep the action reversible.
