---
id: 0009
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.827468+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Await asyncio.sleep(0) before asserting on create_task() side effects

After triggering fire-and-forget async tasks via `asyncio.create_task()`, yield the event loop before making assertions.

```python
task = asyncio.create_task(fn())
await asyncio.sleep(0)
mock.assert_called_once()
```

**Why:** Without yielding, the created task has not yet run; assertions on its side effects will fail spuriously and non-deterministically.
