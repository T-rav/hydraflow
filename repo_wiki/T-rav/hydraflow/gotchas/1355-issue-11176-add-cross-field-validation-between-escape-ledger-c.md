---
id: 1355
topic: gotchas
source_issue: 11176
source_phase: review
created_at: 2026-08-15T01:02:21.454163+00:00
status: active
corroborations: 1
---

# Add cross-field validation between escape_ledger cap configs

Validate that `escape_ledger_max_diagnoses_per_tick` (ge=1, le=500) is not set below `escape_ledger_max_issues_per_tick` (ge=1, le=20) in `src/config.py`.

If diagnoses-cap < ask-cap, the fairness ordering fix in `src/escape_ledger_loop.py` becomes inert: too few findings get diagnosed to fill the ask budget, so the ask-side ordering never matters.

**Why:** Without a guardrail, an operator can silently disable the escape mechanism that #11176's fix provides, with no error or warning.
