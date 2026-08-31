---
id: 0428
topic: architecture
source_issue: 11548
source_phase: plan
created_at: 2026-08-30T10:39:26.773564+00:00
status: active
corroborations: 1
---

# Skeleton-family loop tests belong in tests/architecture/, not copied per module

Hand-copying `test_worker_name`, `test_kill_switch_short_circuits`, `test_default_interval_*`, `test_do_work_short_circuits_when_kill_switch_disabled` into 11 loop modules created the repo's only duplicate family. Replace with ONE parametrised sweep sited under `tests/architecture/` so `test_guard_enumeration_gate.py` classifies it automatically.

- Registry rows: `(worker_name, build, default_interval, env_key|None)`, `build` resolved by reference from each module's public builder.
- Builders must be renamed public (no `_`-prefixed cross-module import).

**Why:** Architecture-gate auto-classification plus single-site sweep prevents the family from regrowing.
