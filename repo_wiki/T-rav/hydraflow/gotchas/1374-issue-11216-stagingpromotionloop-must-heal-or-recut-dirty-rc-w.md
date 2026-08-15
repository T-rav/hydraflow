---
id: 1374
topic: gotchas
source_issue: 11216
source_phase: plan
created_at: 2026-08-15T05:44:56.799472+00:00
status: active
corroborations: 1
---

# StagingPromotionLoop must heal or recut DIRTY RC within one tick

A DIRTY (conflicting) RC promotion PR must never remain open-and-conflicting at the end of a `StagingPromotionLoop` tick. The loop either heals it (merge `origin/main` into RC head, arch-regen, push) or closes it and opens a fresh RC from staging — both in the same tick.

- `_handle_open_promotion` in `src/staging_promotion_loop.py` needs a DIRTY arm before returning `merge_failed`.

**Why:** Without this invariant, a conflicting RC survives every tick, blocking staging promotion indefinitely (#11179, #11200).
