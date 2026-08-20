---
id: 1520
topic: gotchas
source_issue: 11480
source_phase: plan
created_at: 2026-08-20T06:54:25.786729+00:00
status: active
corroborations: 1
---

# Terminal guards return HUMAN_REQUIRED; LabelDriftWatcherLoop reconciles labels

Place landed-fix guards after the `DECOMPOSED` idempotency check but before decomposition. On a guard hit, return `HUMAN_REQUIRED` (the "skip" remedy): outcome `!= "decomposed"`, no children, no status marker.

- The issue self-closes when the closing keyword processes naturally.
- A stray `human-required` label is reconciled by `LabelDriftWatcherLoop`.

**Why:** Returning a non-decomposed outcome satisfies regression pins without adding a new port method or blocking the natural close-on-keyword flow.
