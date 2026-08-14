---
id: 0309
topic: architecture
source_issue: 11101
source_phase: plan
created_at: 2026-08-14T08:02:28.706685+00:00
status: active
corroborations: 1
---

# Do not clear HealthMonitor dedup markers in TrustFleet

When adding auto-remediation gates to `TrustFleetSanityLoop`, ensure the new layer fires first and leaves `HealthMonitorLoop._check_worker_staleness` dedup markers untouched. **Why:** HealthMonitor restarts stalled loops at a deliberately wider threshold; fighting its bookkeeping will cause the two systems to repeatedly restart or page on the same worker.
