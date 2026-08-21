---
id: 0408
topic: architecture
source_issue: 11458
source_phase: plan
created_at: 2026-08-18T12:25:44.377244+00:00
status: active
corroborations: 1
---

# Reconcile disagreeing vocabulary copies by making owned set a superset

When collapsing multiple hand-maintained copies of a vocabulary set (e.g., resolved issue states across `src/regression_rot_scan.py`, `src/gate_health_loop.py`, `src/epic.py`, `src/workspace_gc_loop.py`), define the owned set in the leaf module as a superset of every current site's values. In #11458 the sites disagreed on whether `CLOSED` belonged; the owner includes it, so no site loses a match.

**Why:** A subset would silently drop matches at sites that previously included the excluded value, causing behavior loss.
