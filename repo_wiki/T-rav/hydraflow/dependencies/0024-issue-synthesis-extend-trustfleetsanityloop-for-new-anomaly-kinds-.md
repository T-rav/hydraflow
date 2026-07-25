---
id: 0024
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:40.535795+00:00
status: active
corroborations: 1
supersedes: 0017,0018,0019,0020,0021
---

# Extend TrustFleetSanityLoop for new anomaly kinds instead of adding a loop

When a new fleet-level symptom needs detection, add a pure detector and wire it into the existing `TrustFleetSanityLoop` tick rather than creating a new loop — it inherits `enabled_cb` + `trust_fleet_sanity_loop_enabled` gating for free, so ADR-0049's per-loop kill-switch requirement doesn't apply.

Example: `detect_hitl_low_severity_pileup` in `src/trust_fleet_anomaly_detectors.py` was added as a sixth detector alongside the existing five, invoked after the per-worker scan in `src/trust_fleet_sanity_loop.py`, filed through the loop's existing `_file_anomaly`/dedup/reconcile machinery and `_ANOMALY_KINDS` registry.

**Why:** avoids duplicating kill-switch wiring, dedup/reconcile logic, and escalation filing that already exist in one place.
