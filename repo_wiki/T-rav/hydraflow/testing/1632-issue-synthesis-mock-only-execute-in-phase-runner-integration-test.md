---
id: 1632
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:43:14.206919+00:00
status: active
corroborations: 1
supersedes: 1549
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real StateTracker, EventBus, and VerificationJudge; mock only the _execute() subprocess boundary with configurable transcript strings.

Example: validate state via StateTracker APIs and EventBus.get_history(), not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats.
