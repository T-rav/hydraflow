---
id: 0286
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:12:03.110620+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Hoist deterministic gates outside LLM retry loops

Run subprocess-based validation (coverage, linting) once after the loop exits, not inside each retry iteration.

- Bad: `for attempt in range(1, max_attempts + 1): ... _run_coverage_delta_check(diff)`
- Good: `result = run_llm_loop(...); if result == PASS: _run_coverage_delta_check(diff)`

Only run the gate when the LLM produced a passing verdict — there is no value in running `make coverage` (~300s) against the same code three times while the LLM retries.

**Why:** Placing an expensive deterministic check inside the retry loop multiplies wall-clock cost by `max_attempts` without any additional signal.
