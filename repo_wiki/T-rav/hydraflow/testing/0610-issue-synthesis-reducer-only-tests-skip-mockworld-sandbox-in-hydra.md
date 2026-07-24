---
id: 0610
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.585081+00:00
status: active
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext.test.jsx

Pure reducer changes confined to `src/ui/src/context/HydraFlowContext.jsx` (no Ports, loops, or orchestrator touched) are tested with Vitest unit tests alone in `src/ui/src/context/__tests__/HydraFlowContext.test.jsx`, following the existing `EPIC_READY`/`EPIC_RELEASING` 3As style (arrange state → dispatch action → assert one outcome). Per `docs/standards/testing/README.md`'s full pyramid rule, this is a deliberate exception: MockWorld and sandbox e2e apply to cross-phase/loop integration, which a client-side reducer merge doesn't touch.

**Why:** clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
