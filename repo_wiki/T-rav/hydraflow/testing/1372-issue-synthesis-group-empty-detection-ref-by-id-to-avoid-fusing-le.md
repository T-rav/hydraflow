---
id: 1372
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.377915+00:00
status: superseded
corroborations: 1
supersedes: 1298
superseded_by: 1447
---

# Group empty detection_ref by id to avoid fusing legacy rows

In `latest_by_escape` (src/escape/metrics.py), rows with empty `detection_ref` (legacy/malformed) must fall back to grouping by `id`, not by the empty string.

Example: use `key = detection_ref or id` so each empty-ref row stays distinct. Naive `groupby(detection_ref)` would merge all empty-ref rows into one escape.

**Why:** Legacy rows parse `detection_ref` to `""`; fusing them produces a single phantom escape that corrupts `encoded_summary().total` and `rolling_escape_count`.
