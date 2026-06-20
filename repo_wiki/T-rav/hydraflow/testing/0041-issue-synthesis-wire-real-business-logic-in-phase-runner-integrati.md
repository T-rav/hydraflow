---
id: 0041
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.211710+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Wire real business logic in phase-runner integration tests

Use real `StateTracker`, `EventBus`, and `VerificationJudge` instances in phase-runner integration tests; mock only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing.

Validate via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide mismatches between transcript parsing logic and real output formats — exactly the bugs integration tests exist to catch.
