---
id: 0956
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.542323+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Mock only _execute() in phase-runner integration tests

In phase-runner integration tests, wire real StateTracker, EventBus, and VerificationJudge. Mock only the _execute() subprocess boundary with configurable transcript strings.

Example: validate state via StateTracker APIs and EventBus.get_history(), not mock call assertions.

**Why:** Fully-mocked runners hide parser mismatches between test transcripts and real output formats that only real parsers would catch.
