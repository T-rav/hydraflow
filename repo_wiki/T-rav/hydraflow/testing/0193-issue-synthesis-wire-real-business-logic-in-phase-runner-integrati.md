---
id: 0193
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.786329+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Wire real business logic in phase-runner integration tests

Use real `StateTracker`, `EventBus`, and `VerificationJudge` instances in phase-runner integration tests; mock only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing. Validate via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide mismatches between transcript parsing logic and real output formats — exactly the bugs integration tests exist to catch.
