---
id: 1563
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.326685+00:00
status: active
corroborations: 1
supersedes: 1481
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext

Pure reducer changes confined to src/ui/src/context/HydraFlowContext.jsx are tested with Vitest unit tests alone in src/ui/src/context/__tests__/HydraFlowContext.test.jsx.

Example: follow the existing EPIC_READY/EPIC_RELEASING arrange-act-assert style.

**Why:** MockWorld/sandbox apply to cross-phase/loop integration; clarifies when skipping them is correct scoping rather than a shortcut.
