---
id: 1376
topic: gotchas
source_issue: 11216
source_phase: plan
created_at: 2026-08-15T05:44:56.799517+00:00
status: active
corroborations: 1
---

# Dedupe heal attempts per PR to avoid arch-regen loops

A DIRTY RC PR gets at most one heal attempt per PR lifetime. On heal failure or a second DIRTY tick for the same PR, close and recut from staging instead of re-healing.

- `src/staging_promotion_loop.py` tracks healed PRs; `rc_conflict_heal_max_attempts` (default 1) in `src/config.py` bounds it.

**Why:** A permanently-conflicted RC would otherwise loop arch-regen every tick, burning CI without progress.
