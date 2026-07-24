---
id: 0649
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.495846+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext.test.jsx

Pure reducer changes confined to `src/ui/src/context/HydraFlowContext.jsx` (no Ports, loops, or orchestrator touched) are tested with Vitest unit tests alone in `src/ui/src/context/__tests__/HydraFlowContext.test.jsx`, following the existing `EPIC_READY`/`EPIC_RELEASING` 3As style (arrange state → dispatch action → assert one outcome). Per `docs/standards/testing/README.md`'s full pyramid rule, this is a deliberate exception: MockWorld and sandbox e2e apply to cross-phase/loop integration, which a client-side reducer merge doesn't touch.

**Why:** clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
