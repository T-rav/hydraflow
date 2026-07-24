---
id: 0711
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.892354+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (`is_shared_infra`) plus one `logger.warning` call inside an existing loop (`adr_reviewer.py`'s existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test under the ADR-testing standard.

Example: only unit tests across `tests/test_adr_drift.py`, `tests/test_adr_pre_validator.py`, `tests/test_adr_reviewer.py`, plus a `tests/regressions/` pin.

**Why:** the `docs/standards/testing/README.md` full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead the plan explicitly opted out of.
