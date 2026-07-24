---
id: 0760
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.928406+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# New ADR-authoring aids belong in soft report sections, not CI gates

Author-facing nudges (like a `## Symbol-Granularity Nudges` section in `docs/arch/generated/adr_xref.md` via `src/arch/generators/adr_cross_reference.py`) should render as a visible section that can read "None", never as a build failure.

Example: this mirrors the stalled #10411 lesson: don't add a hard gate for something that's advisory, and don't block merge on background-run signals.

**Why:** turning an authoring suggestion into a hard CI failure punishes valid bare citations to non-owned shared infra and creates false-positive blockers similar to what stalled #10411.
