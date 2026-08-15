---
id: 2130
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.364260+00:00
status: active
corroborations: 1
supersedes: 2014
---

# src/ burn-down helpers take today as a parameter, never date.today()

Pure burn-down and schedule-validation helpers in `src/prompt_fitness.py` must accept an explicit `today: date` parameter. Never call `date.today()` inside `src/`.

Example: `src/` owns the convention; tests assert on explicit dates. Same direction as existing `check_is_tautological` pattern.

**Why:** Any `date.today()` in `src/` makes schedule-guard tests time-dependent and flaky.
