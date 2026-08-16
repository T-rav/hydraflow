---
id: 0223
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:27:56.450204+00:00
status: superseded
corroborations: 1
supersedes: 0208
superseded_by: 0239
---

# Extend TrustFleetSanityLoop for new anomaly kinds, not a new loop

When a new fleet-level symptom needs detection, add a pure detector and wire it into the existing `TrustFleetSanityLoop` tick rather than creating a new loop — it inherits `enabled_cb` + `trust_fleet_sanity_loop_enabled` gating for free, so ADR-0049's per-loop kill-switch requirement doesn't apply.

Example: `detect_hitl_low_severity_pileup` in `src/trust_fleet_anomaly_detectors.py` was added as a sixth detector in `src/trust_fleet_sanity_loop.py`. See also: dependencies — Extend DependabotMergeLoop for green-PR merging, not a new loop.

**Why:** Avoids duplicating kill-switch wiring, dedup/reconcile logic, and escalation filing that already exist in one place.
