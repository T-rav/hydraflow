---
id: 0266
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.484478+00:00
status: superseded
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
superseded_by: 0295
---

# Integration test runners: mock only _execute(), wire real logic

In phase-runner integration tests, wire real `StateTracker`, `EventBus`, `VerificationJudge`, and `RetrospectiveCollector`. Mock only the `_execute()` subprocess boundary with configurable transcript strings.

Validate state via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
