---
id: 0070
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.271434+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Wire real business logic in phase-runner integration tests

Use real `StateTracker`, `EventBus`, and `VerificationJudge` instances in phase-runner integration tests; mock only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing. Validate via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide mismatches between transcript parsing logic and real output formats — exactly the bugs integration tests exist to catch.
