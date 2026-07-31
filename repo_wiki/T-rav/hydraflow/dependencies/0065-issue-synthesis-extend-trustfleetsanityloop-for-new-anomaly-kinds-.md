---
id: 0065
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:25.998755+00:00
status: active
corroborations: 1
supersedes: 0059
---

# Extend TrustFleetSanityLoop for new anomaly kinds, not a new loop

When a new fleet-level symptom needs detection, add a pure detector and wire it into the existing `TrustFleetSanityLoop` tick rather than creating a new loop — it inherits `enabled_cb` + `trust_fleet_sanity_loop_enabled` gating for free, so ADR-0049's per-loop kill-switch requirement doesn't apply.

Example: `detect_hitl_low_severity_pileup` in `src/trust_fleet_anomaly_detectors.py` was added as a sixth detector, invoked after the per-worker scan in `src/trust_fleet_sanity_loop.py`. See also: dependencies — DependabotMergeLoop merges any green PR, not just Dependabot's.

**Why:** Avoids duplicating kill-switch wiring, dedup/reconcile logic, and escalation filing that already exist in one place.
