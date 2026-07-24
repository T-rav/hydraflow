---
id: 0569
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.416825+00:00
status: active
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, and `VerificationJudge`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
