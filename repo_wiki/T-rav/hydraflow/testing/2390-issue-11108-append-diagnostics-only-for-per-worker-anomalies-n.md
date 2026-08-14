---
id: 2390
topic: testing
source_issue: 11108
source_phase: plan
created_at: 2026-08-14T09:10:42.283916+00:00
status: active
corroborations: 1
---

# Append diagnostics only for per-worker anomalies, not fleet-wide

In `_file_anomaly` (`src/trust_fleet_sanity_loop.py`), append `### Auto-captured diagnostics` only when `worker != "fleet"`. Fleet-wide kinds like `hitl_composition` skip the section entirely.

- Per-worker staleness → five subsections below `### Detector output`.
- Fleet-wide `hitl_composition` → body unchanged.

**Why:** Fleet-wide anomalies have no single worker's trace files or scheduler marker to inspect; injecting per-worker diagnostics would produce all-unavailable noise.
