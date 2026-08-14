---
id: 1293
topic: gotchas
source_issue: 11121
source_phase: plan
created_at: 2026-08-14T10:59:17.950981+00:00
status: active
corroborations: 1
---

# Route env floats to plain table, not _ENV_FLOAT_RATIO_OVERRIDES

New float config fields outside [0, 1] go in the plain float env table, not `_ENV_FLOAT_RATIO_OVERRIDES`.

Example: `loop_anomaly_unproductive_min_hours` (default 12.0, range [0.5, 168]) must avoid the ratio table because that table's generic test does `default + 1.0` and assumes bounded [0, 1] semantics.

**Why:** Misrouting produces test failures or silently wrong validation bounds for non-ratio floats.
