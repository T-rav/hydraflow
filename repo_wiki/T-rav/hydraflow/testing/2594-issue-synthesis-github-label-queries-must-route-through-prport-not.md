---
id: 2594
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:52.017533+00:00
status: active
corroborations: 1
supersedes: 2413
---

# GitHub label queries must route through PRPort, not subprocess

`list_issues_by_label` lives on `PRPort`. Trust fleet label queries in `_reconcile_closed_escalations`, `_collect_hitl_items` (`src/trust_fleet_sanity_loop.py`), and the dashboard anomaly reader (`src/dashboard_routes/_trust_routes.py`) must go through this port — never introduce a new `subprocess` call.

**Why:** Bypassing `PRPort` breaks the `MockWorld`/`FakeGitHub` test-port swap and creates untestable network paths inside the loop.
