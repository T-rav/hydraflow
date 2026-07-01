---
id: 0019
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409744+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Integration test runners: mock only _execute(), wire real logic

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, `VerificationJudge`, and `RetrospectiveCollector`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Validate state via `StateTracker` APIs and `EventBus.get_history()`.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
