---
id: 0024
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.695205+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Omitting `await` on an async call silently returns a coroutine object

Always `await` async method calls; storing an unawaited coroutine silently never executes its body.

Example: `result = fetch_data()` stores a `Coroutine` object; `result = await fetch_data()` executes it. Pyright flags the former if a type annotation is present.

**Why:** Unawaited coroutines silently no-op; Pyright only catches them at `make typecheck` time when call sites have annotations.
