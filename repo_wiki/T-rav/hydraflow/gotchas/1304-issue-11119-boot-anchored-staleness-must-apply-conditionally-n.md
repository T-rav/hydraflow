---
id: 1304
topic: gotchas
source_issue: 11119
source_phase: plan
created_at: 2026-08-14T12:19:29.537772+00:00
status: active
corroborations: 1
---

# Boot-anchored staleness must apply conditionally, not unconditionally

When adding a boot-grace floor to `detect_staleness` in `src/trust_fleet_anomaly_detectors.py`, anchor elapsed time from `max(last_run, boot_at)` only when `boot_at > last_run`. Apply `loop_anomaly_boot_grace_seconds` as a threshold floor only in the boot-anchored case.

- A loop that ticked after boot is judged from its own `last_run`, not from boot
- The returned `anchor` detail field must distinguish the two cases for testability
- `boot_at` comes from `session_counters.session_start` (stamped by `Orchestrator._start_session`), failing closed to ctor-captured process-boot time

**Why:** Unconditional anchoring means a long-running loop that dies is never flagged — real staleness is swallowed.
