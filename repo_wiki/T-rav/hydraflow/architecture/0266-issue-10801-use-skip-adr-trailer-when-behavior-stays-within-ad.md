---
id: 0266
topic: architecture
source_issue: 10801
source_phase: plan
created_at: 2026-07-28T10:16:18.732722+00:00
status: active
corroborations: 1
---

# Use Skip-ADR trailer when behavior stays within ADR contract

Rule: When a change touches a module cited by an ADR (e.g. `ADR-0045` cites `src/health_monitor_loop.py:HealthMonitorLoop`) but the behavior remains within the documented dead-man-switch contract, add a `Skip-ADR:` commit trailer instead of amending the ADR.

**Why:** Amending the ADR for in-contract changes bloats the decision record; the trailer provides traceability without churn.
