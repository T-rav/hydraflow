---
id: 2578
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.747526+00:00
status: active
corroborations: 1
supersedes: 2390
---

# Append diagnostics only for per-worker anomalies, not fleet-wide

In `_file_anomaly` (`src/trust_fleet_sanity_loop.py`), append `### Auto-captured diagnostics` only when `worker != "fleet"`. Fleet-wide kinds like `hitl_composition` skip the section entirely.

Example: per-worker staleness → five subsections below `### Detector output`. Fleet-wide `hitl_composition` → body unchanged.

**Why:** Fleet-wide anomalies have no single worker's trace files or scheduler marker to inspect; injecting per-worker diagnostics would produce all-unavailable noise.
