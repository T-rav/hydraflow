---
id: 0679
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.474442+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Extend shared ADR right-sizing test harness, don't fork a new file

When adding a new right-sized ADR citation (e.g. ADR-0012), extend the existing `_RIGHT_SIZED` list and `expected_symbol_owner` dict in `tests/regressions/test_issue_9419_9421_adr_drift.py` rather than writing a new test file or helper.

Example: this harness drives the real `adr_index.parse_adr_file` + `adr_drift.compute_drift` against actual ADR text, so it validates production parsing behavior, not a mock.

**Why:** Duplicating harnesses per-ADR was flagged as a gotchas-audit risk (conftest duplication); the shared parametrized table is the established pattern for this drift-fix class.
