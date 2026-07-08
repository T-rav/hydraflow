---
id: 0183
topic: testing
source_issue: 9567
source_phase: review
created_at: 2026-06-20T09:15:00.395639+00:00
status: active
corroborations: 1
---

# Hoist deterministic gates outside LLM retry loops

Run subprocess-based validation (coverage, linting) once after the loop exits, not inside each retry iteration.

Bad: `for attempt in range(1, max_attempts + 1): ... _run_coverage_delta_check(diff)`
Good: `result = run_llm_loop(...); if result == PASS: _run_coverage_delta_check(diff)`

Only run the gate when the LLM produced a passing verdict — there is no value in running `make coverage` (~300s) against the same code three times while the LLM retries.

**Why:** Placing an expensive deterministic check inside the retry loop multiplies wall-clock cost by `max_attempts` without any additional signal.
