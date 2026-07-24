---
id: 0492
topic: gotchas
source_issue: 10419
source_phase: plan
created_at: 2026-07-24T07:06:01.754939+00:00
status: active
corroborations: 1
---

# ADRValidationResult splits `issues` (gating) from `advisories` (non-gating)

When adding a lint that should nudge but not block, add it to a new `advisories: list[ADRValidationIssue]` field on `ADRValidationResult` in `src/adr_pre_validator.py`, not to `issues`. `passed` and `has_fixable_only` stay keyed on `issues` only, so `adr_reviewer.py`'s council-skip check (`adr_reviewer.py:183`, which skips council on any `issue`) never sees advisories. Example: the #10419 shared-infra bare-citation nudge lives entirely in `advisories`.
**Why:** putting a non-blocking check into `issues` silently turns a warning into a hard gate that blocks council review — this is the #1 pre-mortem risk called out for that change.
