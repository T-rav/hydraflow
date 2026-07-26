---
id: 1012
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.267495+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# Reclassification can re-trigger HITL issue filing via record-id fingerprinting

The escape ledger's surfacing fingerprint is keyed on record id, which changes when a commit is reclassified (e.g. `bug-issue` → `regression-pin` after a detector fix). A re-baseline rewind that re-reads and reclassifies historical commits can therefore re-file HITL issues that were already surfaced under the old classification — potentially duplicating issues like #10498/#10499 and burning `escape_ledger_max_issues_per_tick` on repeats rather than new escapes. Any re-baseline change (`DETECTOR_GENERATION` rewind in `escape_ledger_loop.py`) must include a test proving no double-filing across a reclassification.

**Why:** fingerprint-on-id is a hidden coupling between classification correctness and issue-filing idempotency that only surfaces when the classifier itself changes.
