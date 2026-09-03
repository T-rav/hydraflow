---
id: 1573
topic: gotchas
source_issue: 12059
source_phase: plan
created_at: 2026-09-02T22:09:40.835357+00:00
status: active
corroborations: 1
---

# Reopened regression issues need epic-child label exemption from stale-close

Reopened issues must carry `hydraflow-epic-child` label in `StaleIssueLoop.exclude_labels` to survive the auto-close sweep. `StaleIssueLoop._do_work` (in `src/stale_issue_loop.py`) closes open issues without pipeline stage labels after `stale_days` (30 quiet days). Without this P2 exemption, reopened pins silently re-close and rot recurs. Example: missing `epic_child_label` causes reopened issues to return as `orphaned_red` after the quiet window. Why: Without explicit exemption, regression-fix work creates only temporary relief.
