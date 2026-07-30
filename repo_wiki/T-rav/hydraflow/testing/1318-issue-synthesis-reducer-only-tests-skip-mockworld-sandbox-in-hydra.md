---
id: 1318
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.284828+00:00
status: superseded
corroborations: 1
supersedes: 1244
superseded_by: 1393
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext

Pure reducer changes confined to src/ui/src/context/HydraFlowContext.jsx are tested with Vitest unit tests alone in src/ui/src/context/__tests__/HydraFlowContext.test.jsx.

Example: follow the existing EPIC_READY/EPIC_RELEASING arrange-act-assert style. Per docs/standards/testing/README.md, this is a deliberate exception since MockWorld/sandbox apply to cross-phase/loop integration.

**Why:** Clarifies when skipping MockWorld/sandbox is correct scoping rather than a shortcut that violates the load-bearing test-pyramid rule.
