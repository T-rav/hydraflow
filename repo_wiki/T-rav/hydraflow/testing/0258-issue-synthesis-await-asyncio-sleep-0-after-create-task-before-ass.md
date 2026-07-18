---
id: 0258
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.480357+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Await asyncio.sleep(0) after create_task() before asserting

After triggering a fire-and-forget task, yield one event loop tick before asserting.

```python
task = asyncio.create_task(fn())
await asyncio.sleep(0)
mock.assert_called_once()
```

**Why:** Without yielding, the scheduled task has not run yet; assertions fire on stale state and produce false negatives.
