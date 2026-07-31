---
id: 1236
topic: gotchas
source_issue: 10889
source_phase: plan
created_at: 2026-07-31T10:36:59.292304+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# workspace._FETCH_LOCKS and _WORKTREE_LOCKS leak dead-loop locks

`workspace._FETCH_LOCKS` and `workspace._WORKTREE_LOCKS` hold `asyncio.Lock` objects bound to the event loop active at creation time. When a test ends, its event loop dies; locks persisting into the next test raise `RuntimeError: bound to a different event loop`. These globals must be in the reset table — the hazard is functional, not cosmetic.

**Why:** Cross-test `asyncio.Lock` reuse produces cryptic async failures under xdist worker scheduling.
