---
id: 0264
topic: architecture
source_issue: 10801
source_phase: plan
created_at: 2026-07-28T10:16:18.732704+00:00
status: active
corroborations: 1
---

# Invariant tests must read config fields at runtime, not hardcode tables

Rule: Parametrized invariant tests over `TRUST_LOOP_WORKERS` must source intervals via `getattr(cfg, f"{worker}_interval")` and `cycle_timeout` at runtime. If a config field is missing, fail loudly so the new loop is wired, not silently skipped.

- `tests/architecture/test_trust_loop_stall_remediation_gap.py` derives thresholds dynamically per worker
- No hardcoded interval table anywhere in the test

**Why:** A hardcoded interval table rots the first time a loop's default changes, silently letting a new trust loop evade the gap bound — exactly the failure mode the invariant exists to prevent.
