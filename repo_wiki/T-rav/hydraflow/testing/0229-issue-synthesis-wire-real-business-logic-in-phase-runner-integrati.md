---
id: 0229
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:14:32.517572+00:00
status: active
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
---

# Wire real business logic in phase-runner integration tests

Wire real `StateTracker`, `EventBus`, `VerificationJudge`, and `RetrospectiveCollector`. Mock only the `_execute()` subprocess boundary with configurable transcript strings. Validate via `StateTracker` APIs and `EventBus.get_history()`, not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats — exactly the bugs integration tests exist to catch.
