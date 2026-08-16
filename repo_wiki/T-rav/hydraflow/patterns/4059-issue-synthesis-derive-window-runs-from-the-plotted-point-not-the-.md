---
id: 4059
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:41:45.250812+00:00
status: active
corroborations: 1
supersedes: 3913
---

# Derive window_runs from the plotted point, not the nominal constant

Metadata describing a chart must reflect the data actually plotted, not a configuration constant. In `metric_metadata()` (`src/factory_health.py`), derive `window_runs` from `window_end - window_start + 1` of the rolling-average series's last point; fall back to `ROLLING_WINDOW_RUNS` only when the series is empty. Keep the no-arg call returning the nominal constant for back-compat.

**Why:** A popover claiming 10 runs when the plotted point averages 3 is a user-visible lie that erodes trust in Factory Health tiles.
