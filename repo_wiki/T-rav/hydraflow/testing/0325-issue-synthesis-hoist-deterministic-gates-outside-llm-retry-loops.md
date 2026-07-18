---
id: 0325
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.895657+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Hoist deterministic gates outside LLM retry loops

Run subprocess-based validation (coverage, linting) once after the loop exits, not inside each retry iteration.

- Good: `result = run_llm_loop(...); if result == PASS: _run_coverage_delta_check(diff)`
- Only run the gate when the LLM produced a passing verdict — there is no value in running `make coverage` (~300s) against the same code three times while the LLM retries.

**Why:** Placing an expensive deterministic check inside the retry loop multiplies wall-clock cost by `max_attempts` without any additional signal.
