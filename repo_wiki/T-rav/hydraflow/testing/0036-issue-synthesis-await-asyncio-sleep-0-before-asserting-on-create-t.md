---
id: 0036
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.210910+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Await asyncio.sleep(0) before asserting on create_task() side effects

After triggering fire-and-forget async tasks via `asyncio.create_task()`, yield the event loop before making assertions.

```python
task = asyncio.create_task(fn())
await asyncio.sleep(0)
mock.assert_called_once()
```

**Why:** Without yielding, the created task has not yet run; assertions on its side effects will fail spuriously and non-deterministically.
