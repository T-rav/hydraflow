---
id: 0819
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:13:10.085535+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# New ADR-authoring aids belong in soft report sections, not CI gates

Author-facing nudges (like a `## Symbol-Granularity Nudges` section in `docs/arch/generated/adr_xref.md` via `src/arch/generators/adr_cross_reference.py`) should render as a visible section that can read "None", never as a build failure.

Example: this mirrors the stalled #10411 lesson: don't add a hard gate for something that's advisory, and don't block merge on background-run signals.

**Why:** turning an authoring suggestion into a hard CI failure punishes valid bare citations to non-owned shared infra and creates false-positive blockers similar to what stalled #10411.
