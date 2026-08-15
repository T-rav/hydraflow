---
id: 2609
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T08:32:48.886603+00:00
status: superseded
corroborations: 1
supersedes: 2486
superseded_by: 2732
---

# src/ burn-down helpers take today as a parameter, never date.today()

Pure burn-down and schedule-validation helpers in `src/prompt_fitness.py` must accept an explicit `today: date` parameter. Never call `date.today()` inside `src/`.

Example: `src/` owns the convention; tests assert on explicit dates. Same direction as existing `check_is_tautological` pattern.

**Why:** Any `date.today()` in `src/` makes schedule-guard tests time-dependent and flaky.
