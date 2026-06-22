---
id: 0130
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.433929+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Wire real business logic in phase-runner integration tests

Use real `StateTracker`, `EventBus`, and `VerificationJudge` instances in phase-runner integration tests; mock only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing. Validate via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide mismatches between transcript parsing logic and real output formats — exactly the bugs integration tests exist to catch.
