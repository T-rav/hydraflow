---
id: 3913
topic: patterns
source_issue: 11355
source_phase: plan
created_at: 2026-08-16T15:26:00.442009+00:00
status: superseded
corroborations: 1
superseded_by: 4059
---

# Derive window_runs from the plotted point, not the nominal constant

Rule: Metadata describing a chart must reflect the data actually plotted, not a configuration constant. In `metric_metadata()` (`src/factory_health.py`), derive `window_runs` from `window_end - window_start + 1` of the rolling-average series's last point; fall back to `ROLLING_WINDOW_RUNS` only when the series is empty. Keep the no-arg call returning the nominal constant for back-compat.

**Why:** A popover claiming 10 runs when the plotted point averages 3 is a user-visible lie that erodes trust in Factory Health tiles.
