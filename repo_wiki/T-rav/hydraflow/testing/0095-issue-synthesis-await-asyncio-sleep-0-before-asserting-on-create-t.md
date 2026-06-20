---
id: 0095
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.080465+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Await asyncio.sleep(0) before asserting on create_task() side effects

After triggering fire-and-forget async tasks via `asyncio.create_task()`, yield the event loop before making assertions.

```python
task = asyncio.create_task(fn())
await asyncio.sleep(0)
mock.assert_called_once()
```

**Why:** Without yielding, the created task has not yet run; assertions on its side effects will fail spuriously and non-deterministically.
