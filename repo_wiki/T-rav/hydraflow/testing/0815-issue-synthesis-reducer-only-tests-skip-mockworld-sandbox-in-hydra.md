---
id: 0815
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.188035+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext.test.jsx

Pure reducer changes confined to `src/ui/src/context/HydraFlowContext.jsx` (no Ports, loops, or orchestrator touched) are tested with Vitest unit tests alone in `src/ui/src/context/__tests__/HydraFlowContext.test.jsx`.

Example: follow the existing `EPIC_READY`/`EPIC_RELEASING` 3As style (arrange state → dispatch action → assert one outcome). Per `docs/standards/testing/README.md`'s full pyramid rule, this is a deliberate exception since MockWorld/sandbox apply to cross-phase/loop integration.

**Why:** clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
