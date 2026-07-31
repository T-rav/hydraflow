---
id: 1250
topic: gotchas
source_issue: 10907
source_phase: plan
created_at: 2026-07-31T13:13:56.125087+00:00
status: active
corroborations: 1
---

# Circuit breaker kill-switch clears trip state, not thresholds

Rule: `set_gh_circuit_breaker_enabled(False)` in `src/subprocess_util.py` must call `CircuitBreaker.reset()` (`src/circuit_breaker.py:63`) to clear trip state, but must NOT discard `max_failures`/`reset_timeout` configuration.

- Disable → re-enable after an OPEN window allows the next gh call through.
- Thresholds survive the disable cycle.

**Why:** an operator disable→enable on a stuck-OPEN breaker should resume traffic cleanly; silently reopening to a down GitHub because thresholds were zeroed is a worse failure mode than a stuck breaker.
