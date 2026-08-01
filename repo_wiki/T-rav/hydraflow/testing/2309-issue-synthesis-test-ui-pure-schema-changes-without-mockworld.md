---
id: 2309
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.992201+00:00
status: active
corroborations: 1
supersedes: 2164
---

# Test UI + pure schema changes without MockWorld

Skip MockWorld scenarios for changes that cross no phase/orchestrator boundary and only touch UI views and pure schema-metadata fields. For UI + schema additions, rely on Vitest for component logic (e.g. `model/__tests__/workflowConfig.test.js`) and a single browser scenario in `tests/scenarios/browser/scenarios/` for e2e coverage. See also: testing — ADR-text + static/unit test fixes skip MockWorld/e2e.

**Why:** MockWorld adds unnecessary overhead and test latency for UI/metadata-only changes where standard component tests provide sufficient coverage.
