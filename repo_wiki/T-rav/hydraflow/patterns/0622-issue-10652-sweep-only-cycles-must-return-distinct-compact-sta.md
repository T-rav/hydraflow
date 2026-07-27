---
id: 0622
topic: patterns
source_issue: 10652
source_phase: plan
created_at: 2026-07-26T16:08:03.465321+00:00
status: active
corroborations: 1
---

# Sweep-only cycles must return distinct compact stats, never zeroed metrics

Fast-tick cycles that skip heavy checks must return a small distinct details dict, not a full stats payload with zeroed trend values. Returning zeroed first-pass rate or trend metrics makes dashboards read 0% during sweep-only cycles.

- `HealthMonitorLoop` sweep-only cycles return compact status
- Heavy-pass cycles return the full metrics dict

**Why:** Dashboards and Sentry metrics interpret zeroed fields as real measurements, producing false alerts on every sweep tick.
