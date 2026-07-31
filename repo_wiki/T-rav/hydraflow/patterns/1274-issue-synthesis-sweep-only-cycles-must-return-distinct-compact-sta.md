---
id: 1274
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:41:39.756683+00:00
status: superseded
corroborations: 1
supersedes: 1203
superseded_by: 1348
---

# Sweep-only cycles must return distinct compact stats, not zeroed

Fast-tick cycles that skip heavy checks must return a small distinct details dict, not a full stats payload with zeroed trend values.

Example: `HealthMonitorLoop` sweep-only cycles return compact status; heavy-pass cycles return the full metrics dict.

**Why:** Dashboards and Sentry metrics interpret zeroed fields as real measurements, producing false alerts on every sweep tick.
