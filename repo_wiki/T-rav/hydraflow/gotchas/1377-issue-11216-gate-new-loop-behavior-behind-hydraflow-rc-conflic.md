---
id: 1377
topic: gotchas
source_issue: 11216
source_phase: plan
created_at: 2026-08-15T05:44:56.799524+00:00
status: active
corroborations: 1
---

# Gate new loop behavior behind HYDRAFLOW_RC_CONFLICT_HEAL_ENABLED

New `StagingPromotionLoop` arms must be kill-switched via config with env override so production can restore prior behavior without a redeploy.

- `rc_conflict_heal_enabled` (default True) in `src/config.py`, overridable via `HYDRAFLOW_RC_CONFLICT_HEAL_ENABLED=false`. When off, the DIRTY arm is skipped and `merge_failed` is returned as before.

**Why:** Loop changes are high-blast-radius; a kill-switch allows instant rollback if the heal logic misfires in production.
