---
id: 0584
topic: testing
source_issue: 10314
source_phase: plan
created_at: 2026-07-22T18:34:32.045609+00:00
status: superseded
corroborations: 1
superseded_by: 0593
---

# Reducer-only unit tests in HydraFlowContext.test.jsx skip MockWorld/sandbox layers

Pure reducer changes confined to `src/ui/src/context/HydraFlowContext.jsx` (no Ports, loops, or orchestrator touched) are tested with Vitest unit tests alone in `src/ui/src/context/__tests__/HydraFlowContext.test.jsx`, following the existing `EPIC_READY`/`EPIC_RELEASING` 3As style (arrange state → dispatch action → assert one outcome). Per `docs/standards/testing/README.md`'s full pyramid rule, this is a deliberate exception: MockWorld and sandbox e2e apply to cross-phase/loop integration, which a client-side reducer merge doesn't touch.

**Why:** clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
