---
id: 4069
topic: patterns
source_issue: 11442
source_phase: plan
created_at: 2026-08-18T08:00:27.527752+00:00
status: active
corroborations: 1
---

# Host drift-sensor checks on existing loops, not new runners

Prefer a hosted async actuator over registering a new loop/runner. Write a free `async def` with injected `pr_manager`/`dedup`/`event_bus`, never raise, and call it from an existing loop's `_do_work`. Precedent: `cost_budget_alerts.check_daily_budget` mirrored in `src/token_drift_filing.py` and hosted on `ErosionMetricsLoop._do_work` (`src/erosion_metrics_loop.py`). The actuator inherits the host's `*_enabled`/`dry_run` gates — ADR-0049 kill-switches are for new loops/runners only.

**Why:** New loops add operational surface (new cadence, config knobs, kill-switches); a hosted actuator reuses an existing 86400s tick with zero new dependencies.
