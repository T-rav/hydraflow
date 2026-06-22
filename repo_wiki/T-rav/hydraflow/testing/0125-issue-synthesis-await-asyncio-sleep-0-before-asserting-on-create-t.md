---
id: 0125
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.432442+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Await asyncio.sleep(0) before asserting on create_task() side effects

After triggering fire-and-forget async tasks via `asyncio.create_task()`, yield the event loop before making assertions.

```python
task = asyncio.create_task(fn())
await asyncio.sleep(0)
mock.assert_called_once()
```

**Why:** Without yielding, the created task has not yet run; assertions on its side effects will fail spuriously and non-deterministically.
