---
id: 0154
topic: architecture
source_issue: 10306
source_phase: plan
created_at: 2026-07-24T03:48:07.536888+00:00
status: active
corroborations: 1
---

# Preserve load-bearing filter controls when replacing a table with a card grid

When gutting a sortable/filterable table (e.g. `OutcomesPanel` in `IssueHistoryPanel.jsx`) for a card layout, keep the filter pipeline and testids intact and only remove column sort/drag machinery — don't drop operator-facing controls as part of the rewrite.

Example: range/status/outcome/search/epicOnly filters and the `outcome-filter` testid stay; only the table body and its column sort/drag code are replaced with `IssueOutcomeCard`/`EpicOutcomeCard`.

**Why:** the #10306 plan flags silently dropping the sortable table as its top pre-mortem risk — it loses real operator function even though visually the page still "works."
