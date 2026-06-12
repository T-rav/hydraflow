---
id: 0007
topic: testing
source_issue: 9441
source_phase: review
created_at: 2026-06-12T13:54:23.578695+00:00
status: active
corroborations: 1
---

# New loop requires MockWorld.run_<loop_name>() shim or Tier-1 parity fails

Every new loop needs a `run_<loop_name>()` method on `MockWorld` in `tests/scenarios/fakes/mock_world.py`. Without it, `LoopCatalog` cannot route the loop and Tier-1 parity tests raise `Unknown loop` at runtime.

- Example: `PipelinePoller` needs `MockWorld.run_pipeline_poller()`.
- Include the shim as an explicit deliverable in any implementation plan for a new loop.

**Why:** The gap is invisible until `make scenario` runs — the missing registration does not fail at import, only at test execution.
