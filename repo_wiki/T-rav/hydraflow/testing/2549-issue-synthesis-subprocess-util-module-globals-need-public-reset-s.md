---
id: 2549
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.302447+00:00
status: active
corroborations: 1
supersedes: 2360
---

# subprocess_util module globals need public reset seams

Every process-global in `src/subprocess_util.py` that tests can mutate needs a public `reset_*()` function mirroring its `set_*()` counterpart.

Example: `set_time_source`/`reset_time_source` at `:91-101`; `set_gh_circuit_breaker_enabled`/`reset_gh_circuit_breaker` near `:157`. The conftest autouse fixture (`tests/conftest.py::_reset_gh_semaphore`) calls the public function in setup AND teardown — never assigns `_`-prefixed globals across module boundaries.

**Why:** Without a public seam, class-local fixtures proliferate and a test that opens a breaker leaks `CircuitBreakerOpenError` into unrelated tests.
