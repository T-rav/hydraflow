---
id: 1324
topic: gotchas
source_issue: 11160
source_phase: plan
created_at: 2026-08-14T18:34:20.225983+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Re-read read_latest_index() after appending resolution rows in reconcile

In `_reconcile_surfaced_issues`, call `read_latest_index()` AFTER diagnosis completes so `answered_surfacings` sees the new resolution row. If the index is read before diagnosis, the appended `RESOLVED_ENCODED` row is invisible and open links never close.

**Why:** The collapsed index is a point-in-time snapshot; resolution rows appended after the read won't appear in `answered_surfacings`.
