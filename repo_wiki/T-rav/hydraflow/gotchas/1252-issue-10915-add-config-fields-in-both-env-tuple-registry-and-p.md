---
id: 1252
topic: gotchas
source_issue: 10915
source_phase: plan
created_at: 2026-07-31T15:36:39.647862+00:00
status: active
corroborations: 1
---

# Add config fields in both env-tuple registry and pydantic Field block

New config fields in `src/config.py` must appear in both the env-tuple registry (~L250) and the pydantic `Field` block (~L2141), mirroring existing fields like `erosion_metrics_max_issues_per_tick`.

- Example: `setpoint_max_findings_per_tick` (default 3, ge=1, le=20) and `setpoint_min_baseline_windows` (default 8, ge=2).
- Both fields are additive with defaults; nothing reads them until a consumer lands.

**Why:** The two registration sites serve different code paths; a field present in only one is invisible to the other consumer, causing silent config-lookup failures.
