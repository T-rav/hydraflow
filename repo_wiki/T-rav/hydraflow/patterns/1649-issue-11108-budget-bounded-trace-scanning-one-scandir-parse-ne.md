---
id: 1649
topic: patterns
source_issue: 11108
source_phase: plan
created_at: 2026-08-14T09:10:42.283926+00:00
status: active
corroborations: 1
---

# Budget-bounded trace scanning: one scandir, parse newest N only

To stay inside `trust_fleet_diagnostics_budget_seconds` under large trace counts, perform a single `scandir`, select the newest N files by filename (where N = `trust_fleet_diagnostics_runs`, default 5), parse only those, and re-check the deadline before each section.

- 2000 trace files → scan dir once, sort by name, take top 5.
- Each section re-checks deadline before rendering.

**Why:** Parsing every historical trace file blows the 2.0s budget; filename-sorted newest-N gives the relevant runs at O(1) parse cost.
