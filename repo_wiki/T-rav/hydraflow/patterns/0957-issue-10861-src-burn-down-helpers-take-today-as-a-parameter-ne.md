---
id: 0957
topic: patterns
source_issue: 10861
source_phase: plan
created_at: 2026-07-31T01:46:44.758662+00:00
status: superseded
corroborations: 1
superseded_by: 1021
---

# src/ burn-down helpers take today as a parameter, never date.today()

Pure burn-down and schedule-validation helpers in `src/prompt_fitness.py` must accept an explicit `today: date` parameter. Never call `date.today()` inside `src/`.

- `src/` owns the convention; tests assert on explicit dates.
- Same direction as existing `check_is_tautological` pattern.

**Why:** Deterministic testing and CI reproducibility — any `date.today()` in `src/` makes schedule-guard tests time-dependent and flaky.
