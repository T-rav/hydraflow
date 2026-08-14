---
id: 1276
topic: gotchas
source_issue: 11101
source_phase: plan
created_at: 2026-08-14T08:02:28.706556+00:00
status: active
corroborations: 1
---

# Skip dedup and attempt tracking during remediation deferrals

When auto-remediating before filing an issue in `TrustFleetSanityLoop`, do not touch the dedup set or call `inc_trust_fleet_sanity_attempts` during a deferral. **Why:** Polluting the dedup set or incrementing attempts early prevents the fallback operator-issue filing from ever firing when remediation exhausts, making the 13-day stale window recur invisibly.
