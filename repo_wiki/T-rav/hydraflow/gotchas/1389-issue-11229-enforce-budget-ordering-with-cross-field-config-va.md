---
id: 1389
topic: gotchas
source_issue: 11229
source_phase: plan
created_at: 2026-08-15T07:12:37.006321+00:00
status: active
corroborations: 1
---

# Enforce budget ordering with cross-field config validation

When two config fields have an ordering constraint, enforce it at config load with cross-field validation — not just in field descriptions.

- `src/config.py`: add validation that `escape_ledger_max_diagnoses_per_tick >= escape_ledger_max_issues_per_tick` (wiki gotcha 1355). The description previously documented the defect as fail-safe.

**Why:** Without the guardrail, a diagnose cap below the ask budget silently re-introduces undiagnosed-overflow-to-HITL filing.
