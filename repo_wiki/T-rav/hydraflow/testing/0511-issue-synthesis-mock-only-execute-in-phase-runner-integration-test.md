---
id: 0511
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:10:40.682982+00:00
status: superseded
corroborations: 1
supersedes: 0500,0501,0502,0503,0504,0505,0506,0507,0508,0509
superseded_by: 0520
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, and `VerificationJudge`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: Validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
