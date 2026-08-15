---
id: 3053
topic: patterns
source_issue: 11247
source_phase: plan
created_at: 2026-08-15T20:03:13.665794+00:00
status: active
corroborations: 1
---

# closedAt falls back to updated_at for closed rows; null for open

In `gh_cli_projection.project_issue_row`, a closed row with no seeded `closed_at` reports `updated_at` as `closedAt` — the #9727 convention already in `list_closed_issues_by_label`. Open rows emit `null`, never an empty string.

**Why:** Emitting a timestamp (or empty string) for open rows makes them look closed downstream in fitness scoring; pinning `null` explicitly prevents the mislabel.
