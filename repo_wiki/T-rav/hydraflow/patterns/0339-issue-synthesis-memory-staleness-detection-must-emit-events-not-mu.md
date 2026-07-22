---
id: 0339
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.883016+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Memory staleness detection must emit events, not mutate state

Staleness detection must emit events or log warnings rather than silently deleting or modifying stale entries.

Example: `event_bus.publish(STALE_MEMORY, item_id=item.id, age_days=age)` instead of `self._items.pop(item.id)`.

**Why:** Silent mutation removes the operator's ability to review or override staleness decisions; events keep the action reversible.
