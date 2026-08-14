---
id: 2403
topic: testing
source_issue: 11119
source_phase: plan
created_at: 2026-08-14T12:19:29.537925+00:00
status: active
corroborations: 1
---

# Repurpose trust_fleet_sanity_attempts as consecutive streak, not cumulative

The `trust_fleet_sanity_attempts` field in `src/state/_trust_fleet_sanity.py` is reused as a consecutive-observation streak: keys not observed in a tick are cleared, escalation fires at `loop_anomaly_confirm_ticks` consecutive observations.

- The reset pass must skip already-filed (deduped) keys — clearing them causes re-filing forever
- Clearing nothing makes confirmation meaningless because the counter stays cumulative
- No schema migration is needed because the field is reused in place

Both reset directions need explicit tests.

**Why:** Old state files load unchanged; a cumulative counter would never confirm because it never resets.
