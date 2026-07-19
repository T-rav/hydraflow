---
id: 0160
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.951729+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Omitting `await` on async calls silently returns a coroutine

Always `await` async method calls; storing an unawaited coroutine silently never executes its body.

Example: `result = fetch_data()` stores a `Coroutine` object; `result = await fetch_data()` executes it.

**Why:** Unawaited coroutines silently no-op; Pyright only catches them at `make typecheck` time when call sites have annotations.
