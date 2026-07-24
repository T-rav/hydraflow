---
id: 0686
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.484880+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# ADRValidationResult splits `issues` (gating) from `advisories` (non-gating)

When adding a lint that should nudge but not block, add it to a new `advisories: list[ADRValidationIssue]` field on `ADRValidationResult` in `src/adr_pre_validator.py`, not to `issues`.

Example: `passed` and `has_fixable_only` stay keyed on `issues` only, so `adr_reviewer.py`'s council-skip check (`adr_reviewer.py:183`, which skips council on any `issue`) never sees advisories. The #10419 shared-infra bare-citation nudge lives entirely in `advisories`.

**Why:** Putting a non-blocking check into `issues` silently turns a warning into a hard gate that blocks council review — this is the #1 pre-mortem risk called out for that change.
