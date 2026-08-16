---
id: 1428
topic: gotchas
source_issue: 11307
source_phase: plan
created_at: 2026-08-16T05:25:13.887860+00:00
status: active
corroborations: 1
---

# Guard rearm bounds before SchmittHysteresis in vitals

Guard `rearm < ucl` strictly before constructing `SchmittHysteresis` in vitals engines.
- In `src/objective_change_rate.py`, zero-variance history makes `rearm` and `ucl` equal, causing the constructor to raise.
- Test this edge case directly: steady history must not crash the engine.
**Why:** Prevents hard crashes during flat history windows where variance drops to zero.
