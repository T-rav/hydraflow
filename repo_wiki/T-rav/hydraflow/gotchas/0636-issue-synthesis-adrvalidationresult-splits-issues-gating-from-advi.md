---
id: 0636
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.635789+00:00
status: active
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# ADRValidationResult splits `issues` (gating) from `advisories` (non-gating)

When adding a lint that should nudge but not block, add it to a new `advisories: list[ADRValidationIssue]` field on `ADRValidationResult` in `src/adr_pre_validator.py`, not to `issues`.

Example: `passed` and `has_fixable_only` stay keyed on `issues` only, so `adr_reviewer.py`'s council-skip check (`adr_reviewer.py:183`, which skips council on any `issue`) never sees advisories. The #10419 shared-infra bare-citation nudge lives entirely in `advisories`.

**Why:** Putting a non-blocking check into `issues` silently turns a warning into a hard gate that blocks council review — this is the #1 pre-mortem risk called out for that change.
