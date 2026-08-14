---
id: 1275
topic: gotchas
source_issue: 11101
source_phase: plan
created_at: 2026-08-14T08:02:28.706517+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Deferral across loop ticks requires persisted state, not sleep

When deferring work across loop cycles in hydraflow, use persisted `pending` records with `recheck_after` timestamps instead of `time.sleep` or in-memory waits. Loops run under per-cycle watchdogs. Example: The staleness gate stores `StateData.trust_fleet_remediation` to pause issue filing for one `interval_s` without blocking the loop. **Why:** Sleeping blocks the loop watchdog and halts all other detector processing for that cycle.
