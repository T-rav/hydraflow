---
id: 0395
topic: architecture
source_issue: 11408
source_phase: plan
created_at: 2026-08-18T02:52:22.040825+00:00
status: active
corroborations: 1
---

# retirement_picks: None vs empty-set contract in backlog_budget.py

Rule: In `src/backlog_budget.py:retirement_picks()`, `None`/omitted label-set parameters fall back to module literals (`ADVISORY_STAGE_LABELS`, `PROTECTED_STAGE_LABELS`); an explicit empty set is honoured literally — empty advisory ⇒ no candidates, empty protected ⇒ nothing protected. Use identity checks (`is not None`), not truthy `or`, for both overrides.

Example:
- `advisory_set = advisory_labels if advisory_labels is not None else ADVISORY_STAGE_LABELS`
- Do NOT: `advisory_set = advisory_labels or ADVISORY_STAGE_LABELS`

**Why:** A truthy `or` silently substitutes hardcoded labels when the caller deliberately passed an empty set, closing `hydraflow-find` issues the caller never declared advisory.
