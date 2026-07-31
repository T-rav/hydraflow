---
id: 0270
topic: architecture
source_issue: 10829
source_phase: plan
created_at: 2026-07-31T01:09:02.057425+00:00
status: active
corroborations: 1
---

# Pattern B instruments: sense, record, file findings; never gate or edit

Loop instruments following ADR-0029 Pattern B must never gate CI, open a PR, or edit an ADR. Their write surface is limited to filing bounded issues plus one generated report.

- `SetpointErosionLoop` files `hydraflow-find` issues capped per tick and deduped across ticks.
- `tests/architecture/test_setpoint_write_surface.py` asserts no write path to `docs/adr/`.

**Why:** A measurement instrument that can also edit its target corrupts the signal it is meant to produce.
