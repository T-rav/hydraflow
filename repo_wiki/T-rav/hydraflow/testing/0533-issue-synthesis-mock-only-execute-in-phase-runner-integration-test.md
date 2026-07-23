---
id: 0533
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:34:08.388315+00:00
status: superseded
corroborations: 1
supersedes: 0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530
superseded_by: 0542
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, and `VerificationJudge`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
