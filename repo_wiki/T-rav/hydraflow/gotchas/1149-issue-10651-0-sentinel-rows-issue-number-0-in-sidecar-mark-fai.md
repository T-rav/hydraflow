---
id: 1149
topic: gotchas
source_issue: 10651
source_phase: plan
created_at: 2026-07-26T15:47:34.663698+00:00
status: active
corroborations: 1
---

# 0-sentinel rows (issue number 0) in sidecar mark failed filing attempts

When GitHub `create_issue` returns 0, write a sidecar row with `issue_number = 0` (the 0-sentinel). Every sidecar reader — `open_links()`, reconcile, UI — must tolerate and skip these rows.

- `src/escape/surfaces.py`: `open_links()` requires `issue_number > 0` and skips abandoned fingerprints.
- `SurfacedIssue.from_json_dict` must not choke on rows missing `attempts` or `abandoned_at`.

**Why:** Attempt-tracking rows are infrastructure, not surfaced issues; treating them as real issues would produce dead links and corrupt link counts.
