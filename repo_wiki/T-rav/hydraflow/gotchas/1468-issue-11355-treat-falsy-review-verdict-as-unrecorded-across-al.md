---
id: 1468
topic: gotchas
source_issue: 11355
source_phase: plan
created_at: 2026-08-16T15:26:00.441967+00:00
status: active
corroborations: 1
---

# Treat falsy review_verdict as unrecorded across all panels

Rule: Any falsy `review_verdict` (absent, `None`, `""`) means "unrecorded," not "failed." The `""` sentinel is declared at `src/retrospective.py:39` and written by `model_dump_json`.

- Filter with `if e.review_verdict` (as `_metrics_routes.py:448` already does).
- Exclude unrecorded verdicts from the `first_pass_rate` denominator in `src/factory_health.py`.

**Why:** Counting the sentinel as a failure deflates `first_pass_rate` and corrupts `SecondOrderVitalsLoop._ci_pass_rate`.
