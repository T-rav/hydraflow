---
id: 1272
topic: gotchas
source_issue: 11103
source_phase: plan
created_at: 2026-08-14T07:34:32.949721+00:00
status: active
corroborations: 1
---

# CI leg-selection guards fail silently on leg insertion

Guards that select CI legs positionally — `next(... "-n auto" ...)` or `runs[-1]` — break silently when a new leg is inserted between existing ones. The first symptom is a weakened invariant, not a red test.

- `test_issue_10883.py` used `next(... "-n auto" ...)` to find leg1; a second parallel leg made this ambiguous.
- Fix: identify legs by target/step identity, not ordinal position.
- The terminal serial leg must stay last because a guard requires the real `--cov-fail-under=70` floor on the final pytest step.

**Why:** Positional selection couples test correctness to YAML line order; any leg insertion or reorder silently invalidates the guard without failing.
