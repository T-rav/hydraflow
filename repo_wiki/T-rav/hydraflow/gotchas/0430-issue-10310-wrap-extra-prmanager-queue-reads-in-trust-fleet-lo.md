---
id: 0430
topic: gotchas
source_issue: 10310
source_phase: plan
created_at: 2026-07-24T04:15:36.841901+00:00
status: active
corroborations: 1
---

# Wrap extra PRManager queue reads in trust-fleet loops fail-open

Any new `PRManager` call added inside a `TrustFleetSanityLoop` tick (e.g. `list_issues_by_label`) must be wrapped to fail open — return an empty result and let the cycle complete — mirroring the existing `_reconcile_closed_escalations` pattern.

Example: `_collect_hitl_queue_signal()` in `src/trust_fleet_sanity_loop.py` catches `list_issues_by_label` exceptions and treats them as an empty queue rather than propagating.

**Why:** an unguarded hang or exception on the extra gh/API call would trip the dead-man-switch and stall the whole sanity loop, not just the new detector.
