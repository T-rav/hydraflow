---
id: 1458
topic: testing
source_issue: 10786
source_phase: plan
created_at: 2026-07-28T09:18:05.893395+00:00
status: active
corroborations: 1
---

# Test UI + pure schema changes without MockWorld

Skip MockWorld scenarios for changes that cross no phase/orchestrator boundary and only touch UI views and pure schema-metadata fields. For UI + schema additions, rely on Vitest for component logic (e.g., `model/__tests__/workflowConfig.test.js`) and a single browser scenario in `tests/scenarios/browser/scenarios/` for e2e coverage.

**Why:** MockWorld adds unnecessary overhead and test latency for UI/metadata-only changes where standard component tests provide sufficient coverage.
