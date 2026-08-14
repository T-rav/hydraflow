---
id: 1285
topic: gotchas
source_issue: 11108
source_phase: plan
created_at: 2026-08-14T09:10:42.283890+00:00
status: active
corroborations: 1
---

# Distinguish scheduler-never-fired from cycle-ran-and-failed via marker+heartbeat

Join the durable marker at `memory/.<worker>_last_run` against the heartbeat to classify scheduler state. Skew between the two separates "scheduler never fired" from "cycle ran and failed".

- Marker present, heartbeat stale → cycle ran, then died.
- Marker absent, heartbeat live → scheduler never fired.
- Operator-disabled worker → read as kill-switched.

**Why:** Without this join, a stale loop's failure mode is ambiguous and the auto-retry cannot pick the correct remediation path.
