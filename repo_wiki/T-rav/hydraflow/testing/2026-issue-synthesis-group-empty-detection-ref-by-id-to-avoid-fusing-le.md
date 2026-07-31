---
id: 2026
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.715788+00:00
status: superseded
corroborations: 1
supersedes: 1899
superseded_by: 2155
---

# Group empty detection_ref by id to avoid fusing legacy rows

In latest_by_escape (src/escape/metrics.py), rows with empty detection_ref (legacy/malformed) must fall back to grouping by id, not by the empty string.

Example: use `key = detection_ref or id` so each empty-ref row stays distinct. Naive `groupby(detection_ref)` would merge all empty-ref rows into one escape.

**Why:** Legacy rows parse detection_ref to ''; fusing them produces a single phantom escape that corrupts encoded_summary().total and rolling_escape_count.
