---
id: 0257
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:52:50.696450+00:00
status: superseded
corroborations: 1
supersedes: 0239
superseded_by: 0275
---

# Extend TrustFleetSanityLoop for new anomaly kinds, not a new loop

When a new fleet-level symptom needs detection, add a pure detector and wire it into the existing `TrustFleetSanityLoop` tick rather than creating a new loop.

Example: `detect_hitl_low_severity_pileup` in `src/trust_fleet_anomaly_detectors.py` was added as a sixth detector in `src/trust_fleet_sanity_loop.py`. See also: dependencies — Extend DependabotMergeLoop for green-PR merging, not a new loop.

**Why:** Avoids duplicating kill-switch wiring, dedup/reconcile logic, and escalation filing that already exist in one place.
