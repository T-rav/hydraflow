---
id: 0058
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.906894+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Omitting `await` on an async call silently returns a coroutine object

Always `await` async method calls; storing an unawaited coroutine silently never executes its body.

Example: `result = fetch_data()` stores a `Coroutine` object; `result = await fetch_data()` executes it. Pyright flags the former if a type annotation is present.

See also: gotchas — Store `asyncio.create_task()` results.

**Why:** Unawaited coroutines silently no-op; Pyright only catches them at `make typecheck` time when call sites have annotations.
