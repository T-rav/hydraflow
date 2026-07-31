---
id: 1972
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:52.993975+00:00
status: superseded
corroborations: 1
supersedes: 1845
superseded_by: 2102
---

# Reducer-only tests skip MockWorld/sandbox in HydraFlowContext

Pure reducer changes confined to src/ui/src/context/HydraFlowContext.jsx are tested with Vitest unit tests alone in src/ui/src/context/__tests__/HydraFlowContext.test.jsx.

Example: follow the existing EPIC_READY/EPIC_RELEASING arrange-act-assert style.

**Why:** MockWorld/sandbox apply to cross-phase/loop integration; clarifies when skipping them is correct scoping rather than a shortcut.
