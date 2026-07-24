---
id: 0589
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.265719+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# ADRValidationResult splits `issues` (gating) from `advisories` (non-gating)

When adding a lint that should nudge but not block, add it to a new `advisories: list[ADRValidationIssue]` field on `ADRValidationResult` in `src/adr_pre_validator.py`, not to `issues`.

Example: `passed` and `has_fixable_only` stay keyed on `issues` only, so `adr_reviewer.py`'s council-skip check (`adr_reviewer.py:183`, which skips council on any `issue`) never sees advisories. The #10419 shared-infra bare-citation nudge lives entirely in `advisories`.

**Why:** Putting a non-blocking check into `issues` silently turns a warning into a hard gate that blocks council review — this is the #1 pre-mortem risk called out for that change.
