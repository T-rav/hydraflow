---
id: 0522
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:39:13.363949+00:00
status: active
corroborations: 1
supersedes: 0510,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, and `VerificationJudge`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
