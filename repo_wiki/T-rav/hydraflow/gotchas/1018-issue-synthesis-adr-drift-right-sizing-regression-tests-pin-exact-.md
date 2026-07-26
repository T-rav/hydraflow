---
id: 1018
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.276780+00:00
status: superseded
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
superseded_by: 1039
---

# ADR-drift right-sizing regression tests pin exact symbol owners

`tests/regressions/test_issue_9419_9421_adr_drift.py` maintains a `_RIGHT_SIZED` set and an `expected_symbol_owner` map that must be extended together whenever an ADR's citations are right-sized (e.g. adding entry `97` for ADR-0097). The test asserts the real `parse_adr_file` resolves each qualified citation to a symbol that actually exists on disk (e.g. `ImplementPhase._record_impl_metrics` at src/implement_phase.py:655) — a typo'd or renamed symbol would silently and permanently disable drift detection for that file with no error signal.

**Why:** guards against silent, undetectable suppression of legitimate drift via a wrong symbol name. See also — "Extend shared ADR right-sizing test harness, don't fork a new file" for where new entries go.
