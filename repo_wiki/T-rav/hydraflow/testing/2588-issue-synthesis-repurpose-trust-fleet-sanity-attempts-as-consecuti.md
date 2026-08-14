---
id: 2588
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.904208+00:00
status: active
corroborations: 1
supersedes: 2403
---

# Repurpose trust_fleet_sanity_attempts as consecutive streak

The `trust_fleet_sanity_attempts` field in `src/state/_trust_fleet_sanity.py` is reused as a consecutive-observation streak: keys not observed in a tick are cleared, escalation fires at `loop_anomaly_confirm_ticks` consecutive observations.

Example: the reset pass must skip already-filed (deduped) keys — clearing them causes re-filing forever. Both reset directions need explicit tests.

**Why:** Old state files load unchanged; a cumulative counter would never confirm because it never resets.
