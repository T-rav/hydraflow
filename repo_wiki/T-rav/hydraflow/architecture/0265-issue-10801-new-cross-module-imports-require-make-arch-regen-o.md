---
id: 0265
topic: architecture
source_issue: 10801
source_phase: plan
created_at: 2026-07-28T10:16:18.732712+00:00
status: active
corroborations: 1
---

# New cross-module imports require make arch-regen or CI fails

Rule: Adding any cross-module import to `src/*.py` modules changes the module graph. Run `make arch-regen` before committing, then verify with `make arch-check`.

- Importing `TRUST_LOOP_WORKERS` from `trust_fleet_anomaly_detectors` into `src/health_monitor_loop.py` adds a new module-graph edge
- `docs/arch/generated/*` must be regenerated

**Why:** CI enforces that architecture artifacts match the live module graph; stale artifacts fail `make arch-check` and block merge.
