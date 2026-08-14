---
id: 2233
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.791786+00:00
status: superseded
corroborations: 1
supersedes: 2088
superseded_by: 2423
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real StateTracker, EventBus, and VerificationJudge; mock only the `_execute()` subprocess boundary with configurable transcript strings.

Example: validate state via StateTracker APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats.
