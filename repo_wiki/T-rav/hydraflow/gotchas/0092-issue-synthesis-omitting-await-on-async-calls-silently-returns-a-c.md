---
id: 0092
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.517968+00:00
status: superseded
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
superseded_by: 0112
---

# Omitting `await` on async calls silently returns a coroutine

Always `await` async method calls; storing an unawaited coroutine silently never executes its body.

Example: `result = fetch_data()` stores a `Coroutine` object; `result = await fetch_data()` executes it. Pyright flags the former if a type annotation is present.

**Why:** Unawaited coroutines silently no-op; Pyright only catches them at `make typecheck` time when call sites have annotations.
