---
id: 1225
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T11:05:52.499168+00:00
status: superseded
corroborations: 1
supersedes: 1157
superseded_by: 1296
---

# src/ burn-down helpers take today as a parameter, never date.today()

Pure burn-down and schedule-validation helpers in `src/prompt_fitness.py` must accept an explicit `today: date` parameter. Never call `date.today()` inside `src/`.

Example: `src/` owns the convention; tests assert on explicit dates. Same direction as existing `check_is_tautological` pattern.

**Why:** Deterministic testing and CI reproducibility — any `date.today()` in `src/` makes schedule-guard tests time-dependent and flaky.
