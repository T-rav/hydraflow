---
id: 2667
topic: testing
source_issue: 11296
source_phase: plan
created_at: 2026-08-16T02:48:52.749398+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Drive src/ui JS from pytest via node ESM resolve hook

Regression tests under `tests/regressions/` can exercise `src/ui` modules directly from pytest using the node ESM resolve hook (`vitals.js`/`loops.js` pattern) — no Python reimplementation of `toTimeline`. The JS module is imported and driven in-process; assertions are pytest-side.

**Why:** Duplicating `toTimeline` in Python would create a second vocabulary mirror with its own drift surface; the ESM hook keeps the test against the real implementation that ships.
