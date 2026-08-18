---
id: 1498
topic: gotchas
source_issue: 11424
source_phase: plan
created_at: 2026-08-18T04:14:44.048823+00:00
status: active
corroborations: 1
---

# Use table-driven recurrence guards for multi-site wiring fixes

When fixing the same class of bug across multiple sites, create a parametrized table in a new test file (e.g. `tests/scenarios/catalog/test_collaborator_wiring.py`) with rows of `(loop_name, port_key, private_attr)`.

Each row seeds a sentinel on the port, builds via the catalog, and asserts the sentinel is the private attr. Reverting any single builder edit causes exactly that row to fail — no ambiguity about which site broke.

If a related issue (#11416) lands, merge tables into one file rather than maintaining two.

**Why:** Separate ad-hoc tests per site are brittle and don't cleanly isolate which wiring edit regressed.
