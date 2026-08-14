---
id: 0316
topic: architecture
source_issue: 11121
source_phase: plan
created_at: 2026-08-14T10:59:17.948167+00:00
status: active
corroborations: 1
---

# Public symbols only in trust_fleet_anomaly_detectors.py

Symbols added to `src/trust_fleet_anomaly_detectors.py` must not start with `_`. The module is imported cross-module by `_trust_routes.py` and `trust_fleet_sanity_loop.py`.

Example: `NON_PRODUCTIVE_STATUSES`, `is_non_productive_status()`, `summarize_status_timeline()` — no leading underscores.

**Why:** Python's `from module import *` and conventional private-marking make underscore-prefixed symbols invisible or semantically private to cross-module consumers.
