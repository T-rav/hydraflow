---
id: 0009
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408500+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Await asyncio.sleep(0) after create_task() before asserting

After triggering a fire-and-forget task, yield one event loop tick before asserting:

```python
asyncio.create_task(fn())
await asyncio.sleep(0)
assert mock.called
```

**Why:** Without yielding, the scheduled task has not run yet; assertions fire on stale state and produce false negatives.
