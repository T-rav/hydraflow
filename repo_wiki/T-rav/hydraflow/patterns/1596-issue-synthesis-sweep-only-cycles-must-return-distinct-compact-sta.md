---
id: 1596
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T07:44:05.291037+00:00
status: superseded
corroborations: 1
supersedes: 1511
superseded_by: 1690
---

# Sweep-only cycles must return distinct compact stats, not zeroed

Fast-tick cycles that skip heavy checks must return a small distinct details dict, not a full stats payload with zeroed trend values.

Example: `HealthMonitorLoop` sweep-only cycles return compact status; heavy-pass cycles return the full metrics dict.

**Why:** Dashboards and Sentry metrics interpret zeroed fields as real measurements, producing false alerts on every sweep tick.
