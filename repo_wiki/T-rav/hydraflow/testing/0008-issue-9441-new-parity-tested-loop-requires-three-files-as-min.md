---
id: 0008
topic: testing
source_issue: 9441
source_phase: review
created_at: 2026-06-12T13:54:23.578712+00:00
status: active
corroborations: 1
---

# New parity-tested loop requires three files as minimum deliverables

A loop that meets the test-pyramid standard requires at minimum three separate file deliverables:

1. `tests/scenarios/fakes/mock_world.py` — `run_<loop_name>()` shim
2. `tests/sandbox_scenarios/scenarios/s<N>_<loop_name>.py` — Tier-2 e2e scenario
3. Tier-1 test (either a new `test_<loop>_parity_shim.py` or an entry in `test_sandbox_parity.py`)

**Why:** Each layer catches a different failure mode — unit tests are blind to real-API behavior, MockWorld catches loop integration, sandbox e2e catches docker/UI/wiring. Shipping without any layer is a procedural failure per `docs/standards/testing/README.md`.
