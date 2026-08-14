---
id: 1265
topic: gotchas
source_issue: 11090
source_phase: plan
created_at: 2026-08-14T06:25:31.261865+00:00
status: active
corroborations: 1
---

# Quality lane non-zero exits can vanish in parallel subshells

The UI vitest lane runs inside `( ... ) &` in the quality parallel block. If `exit 1` lands in a subshell the wait loop doesn't collect, `make quality` stays green.

Pin via `tests/test_makefile_quality_order.py` that the blocked branch runs as a background job *before* the wait loop and is actually collected. Verify with a real failing run, not just `make -n`.

**Why:** Parallel-make exit-code swallowing is the top pre-mortem for silent false greens reintroduced by this lane.
