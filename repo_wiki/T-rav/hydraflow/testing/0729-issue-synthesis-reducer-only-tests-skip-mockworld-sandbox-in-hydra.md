---
id: 0729
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.212291+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext.test.jsx

Pure reducer changes confined to `src/ui/src/context/HydraFlowContext.jsx` (no Ports, loops, or orchestrator touched) are tested with Vitest unit tests alone in `src/ui/src/context/__tests__/HydraFlowContext.test.jsx`.

Example: follow the existing `EPIC_READY`/`EPIC_RELEASING` 3As style (arrange state → dispatch action → assert one outcome). Per `docs/standards/testing/README.md`'s full pyramid rule, this is a deliberate exception since MockWorld/sandbox apply to cross-phase/loop integration.

**Why:** clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
