---
id: 1803
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.142738+00:00
status: active
corroborations: 1
supersedes: 1709
---

# Test UI + pure schema changes without MockWorld

Skip MockWorld scenarios for changes that cross no phase/orchestrator boundary and only touch UI views and pure schema-metadata fields. For UI + schema additions, rely on Vitest for component logic (e.g. model/__tests__/workflowConfig.test.js) and a single browser scenario in tests/scenarios/browser/scenarios/ for e2e coverage.

**Why:** MockWorld adds unnecessary overhead and test latency for UI/metadata-only changes where standard component tests provide sufficient coverage.
