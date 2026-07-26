---
id: 0894
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.746247+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# ADRValidationResult splits `issues` (gating) from `advisories` (non-gating)

When adding a lint that should nudge but not block, add it to a new `advisories: list[ADRValidationIssue]` field on `ADRValidationResult` in `src/adr_pre_validator.py`, not to `issues`.

Example: `passed` and `has_fixable_only` stay keyed on `issues` only, so `adr_reviewer.py`'s council-skip check (`adr_reviewer.py:183`, which skips council on any `issue`) never sees advisories. The #10419 shared-infra bare-citation nudge lives entirely in `advisories`.

**Why:** Putting a non-blocking check into `issues` silently turns a warning into a hard gate that blocks council review — this is the #1 pre-mortem risk called out for that change.
