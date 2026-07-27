---
id: 0907
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.760861+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# New ADR-authoring aids belong in soft report sections, not CI gates

Author-facing nudges (like a `## Symbol-Granularity Nudges` section in `docs/arch/generated/adr_xref.md` via `src/arch/generators/adr_cross_reference.py`) should render as a visible section that can read "None", never as a build failure.

Example: this mirrors the stalled #10411 lesson: don't add a hard gate for something that's advisory, and don't block merge on background-run signals.

**Why:** turning an authoring suggestion into a hard CI failure punishes valid bare citations to non-owned shared infra and creates false-positive blockers similar to what stalled #10411.
