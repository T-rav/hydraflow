---
id: 0544
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.119801+00:00
status: active
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, and `VerificationJudge`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
