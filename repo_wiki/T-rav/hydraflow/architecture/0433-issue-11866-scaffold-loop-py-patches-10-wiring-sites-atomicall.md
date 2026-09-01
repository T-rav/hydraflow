---
id: 0433
topic: architecture
source_issue: 11866
source_phase: plan
created_at: 2026-09-01T03:52:25.540780+00:00
status: active
corroborations: 1
---

# scaffold_loop.py patches ~10 wiring sites atomically; hand-finish the rest

Start new background loops with `scripts/scaffold_loop.py <name> --type subprocess`. It patches ~10 wiring sites (`src/config.py`, `src/service_registry.py`, `src/orchestrator.py`, etc.) atomically; hand-finish the remaining sites (e.g., `docs/arch/functional_areas.yml`, `control/fleet.yaml`, scenario catalog).
- The ~7 completeness ratchets (`test_loop_wiring_completeness.py`, `test_loop_kill_switch_completeness.py`, `test_loop_fitness_completeness.py`) must stay green after scaffold.
**Why:** Wiring a loop touches 10+ files; doing it atomically prevents half-wired states that break the ratchet suite.
