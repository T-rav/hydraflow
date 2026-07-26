---
id: 1032
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.467760+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext.test.jsx

Pure reducer changes confined to src/ui/src/context/HydraFlowContext.jsx (no Ports, loops, or orchestrator touched) are tested with Vitest unit tests alone in src/ui/src/context/__tests__/HydraFlowContext.test.jsx.

Example: follow the existing EPIC_READY/EPIC_RELEASING 3As style (arrange state, dispatch action, assert one outcome). Per docs/standards/testing/README.md's full pyramid rule, this is a deliberate exception since MockWorld/sandbox apply to cross-phase/loop integration.

**Why:** clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
