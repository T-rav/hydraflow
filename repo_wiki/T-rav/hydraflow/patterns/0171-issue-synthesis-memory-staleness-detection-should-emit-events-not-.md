---
id: 0171
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.032009+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Memory staleness detection should emit events, not silently mutate state

Staleness detection must emit events or log warnings rather than silently deleting or modifying stale entries.

Example: `event_bus.publish(STALE_MEMORY, item_id=item.id, age_days=age)` instead of `self._items.pop(item.id)`.

**Why:** Silent mutation removes the operator's ability to review or override staleness decisions; events keep the action reversible.
