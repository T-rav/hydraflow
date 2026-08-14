---
id: 2413
topic: testing
source_issue: 11139
source_phase: plan
created_at: 2026-08-14T14:16:51.498125+00:00
status: superseded
corroborations: 1
superseded_by: 2594
---

# GitHub label queries must route through PRPort, not subprocess

`list_issues_by_label` lives on `PRPort`. Trust fleet label queries in `_reconcile_closed_escalations`, `_collect_hitl_items` (`src/trust_fleet_sanity_loop.py`), and the dashboard anomaly reader (`src/dashboard_routes/_trust_routes.py`) must go through this port — never introduce a new `subprocess` call.

**Why:** Bypassing `PRPort` breaks the `MockWorld`/`FakeGitHub` test-port swap and creates untestable network paths inside the loop.
