---
id: 0501
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:43:13.304872+00:00
status: superseded
corroborations: 1
supersedes: 0492,0493,0494,0495,0496,0497,0498,0499
superseded_by: 0510
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, and `VerificationJudge`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: Validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
