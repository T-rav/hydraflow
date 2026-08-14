---
id: 0332
topic: architecture
source_issue: 11165
source_phase: plan
created_at: 2026-08-14T19:36:20.069100+00:00
status: active
corroborations: 1
---

# Public canonical labels vs module-private aliases in trust_fleet_anomaly_detectors

Canonical labels exported from `src/trust_fleet_anomaly_detectors.py` are public (no `_` prefix) — cross-module import is the intended usage pattern. Module-private aliases like `_HITL_QUEUE_LABEL` in `src/trust_fleet_sanity_loop.py` stay private and are only monkeypatched in-module.

- `TRUST_LOOP_ANOMALY_LABEL` and `HITL_QUEUE_LABEL` are the two canonical roots; both have twin grep guards.
- The label *value* never changes through unification — only the sourcing path does, so no migration is needed.

**Why:** Mixing the public/private boundary causes either import errors or accidental cross-module monkeypatch leaks that mask drift.
