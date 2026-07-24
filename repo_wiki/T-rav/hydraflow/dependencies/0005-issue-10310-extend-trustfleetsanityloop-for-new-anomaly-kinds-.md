---
id: 0005
topic: dependencies
source_issue: 10310
source_phase: plan
created_at: 2026-07-24T04:15:36.841870+00:00
status: superseded
corroborations: 1
superseded_by: 0006
---

# Extend TrustFleetSanityLoop for new anomaly kinds instead of adding a loop

When a new fleet-level symptom needs detection, add a pure detector + wire it into the existing `TrustFleetSanityLoop` tick rather than creating a new loop — it inherits `enabled_cb` + `trust_fleet_sanity_loop_enabled` gating for free, so ADR-0049's per-loop kill-switch requirement doesn't apply.

Example: `detect_hitl_low_severity_pileup` in `src/trust_fleet_anomaly_detectors.py` was added as a sixth detector alongside the existing five, invoked once after the per-worker scan in `src/trust_fleet_sanity_loop.py`, filed through the loop's existing `_file_anomaly`/dedup/reconcile machinery and `_ANOMALY_KINDS` registry.

**Why:** avoids duplicating kill-switch wiring, dedup/reconcile logic, and escalation filing that already exist in one place.
