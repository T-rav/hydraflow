---
id: 3422
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.965281+00:00
status: superseded
corroborations: 1
supersedes: 3285
superseded_by: 3569
---

# load_events_since order is not guaranteed — sort before streak math

Always sort events by timestamp before computing trailing streaks or timeline summaries from `load_events_since`.

Example: `_collect_window_metrics` builds a per-worker `(ts, details.status)` timeline and sorts it before calling `summarize_status_timeline()`; `_tally_events` in `_trust_routes.py` does the same.

**Why:** Without sorting, a non-productive streak silently mis-reads as intermittent because out-of-order events fragment the trailing run.
