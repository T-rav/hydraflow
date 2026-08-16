---
id: 2727
topic: testing
source_issue: 11354
source_phase: plan
created_at: 2026-08-16T15:20:51.560195+00:00
status: active
corroborations: 1
---

# Pure frontend changes need only Vitest — MockWorld tier is N/A

Changes touching only `src/ui/` (no orchestrator, runner, Port, or subprocess) require only `cd src/ui && npm test`. The MockWorld tier of the testing pyramid does not apply.

After UI tests pass, run `make quality` from repo root.

**Why:** Avoids unnecessary integration test setup for changes that never cross the frontend/backend boundary.
