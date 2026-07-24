---
id: 0740
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.018398+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Extend shared ADR right-sizing test harness, don't fork a new file

When adding a new right-sized ADR citation (e.g. ADR-0012), extend the existing `_RIGHT_SIZED` list and `expected_symbol_owner` dict in `tests/regressions/test_issue_9419_9421_adr_drift.py` rather than writing a new test file or helper.

Example: this harness drives the real `adr_index.parse_adr_file` + `adr_drift.compute_drift` against actual ADR text, so it validates production parsing behavior, not a mock.

**Why:** Duplicating harnesses per-ADR was flagged as a gotchas-audit risk (conftest duplication); the shared parametrized table is the established pattern for this drift-fix class.
