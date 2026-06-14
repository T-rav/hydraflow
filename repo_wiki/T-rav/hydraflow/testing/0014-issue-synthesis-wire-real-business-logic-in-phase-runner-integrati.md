---
id: 0014
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.828398+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Wire real business logic in phase-runner integration tests

Phase-runner integration tests should use real `StateTracker`, `EventBus`, and `VerificationJudge` instances, mocking only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing.

Validate via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide mismatches between transcript parsing logic and real output formats — exactly the bugs integration tests exist to catch.
