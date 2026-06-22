---
id: 0188
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.784644+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Await asyncio.sleep(0) before asserting on create_task() side effects

After triggering fire-and-forget tasks via `asyncio.create_task()`, yield the event loop before making assertions.

```python
task = asyncio.create_task(fn())
await asyncio.sleep(0)
mock.assert_called_once()
```

**Why:** Without yielding, the created task has not yet run; assertions on its side effects will fail spuriously and non-deterministically.
