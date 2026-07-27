---
id: 1224
topic: testing
source_issue: 10654
source_phase: plan
created_at: 2026-07-26T16:24:44.376095+00:00
status: superseded
corroborations: 1
superseded_by: 1298
---

# Group empty detection_ref by id to avoid fusing legacy rows

In `latest_by_escape`, rows with empty `detection_ref` (legacy/malformed) must fall back to grouping by `id`, not by the empty string.

- Naive `groupby(detection_ref)` would merge all empty-ref rows into one escape.
- Use `key = detection_ref or id` so each empty-ref row stays distinct.

**Why:** Legacy rows parse `detection_ref` to `""`; fusing them produces a single phantom escape that corrupts `encoded_summary().total` and `rolling_escape_count`.
