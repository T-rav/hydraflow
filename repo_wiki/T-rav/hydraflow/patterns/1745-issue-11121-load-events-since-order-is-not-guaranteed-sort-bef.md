---
id: 1745
topic: patterns
source_issue: 11121
source_phase: plan
created_at: 2026-08-14T10:59:17.951035+00:00
status: superseded
corroborations: 1
superseded_by: 1838
---

# load_events_since order is not guaranteed — sort before streak math

Always sort events by timestamp before computing trailing streaks or timeline summaries from `load_events_since`.

Example: `_collect_window_metrics` builds a per-worker `(ts, details.status)` timeline and sorts it before calling `summarize_status_timeline()`; `_tally_events` in `_trust_routes.py` does the same.

**Why:** Without sorting, a non-productive streak silently mis-reads as intermittent because out-of-order events fragment the trailing run.
