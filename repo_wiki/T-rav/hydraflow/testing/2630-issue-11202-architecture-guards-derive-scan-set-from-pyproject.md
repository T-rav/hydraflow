---
id: 2630
topic: testing
source_issue: 11202
source_phase: plan
created_at: 2026-08-15T03:13:32.213203+00:00
status: active
corroborations: 1
---

# Architecture guards: derive scan set from pyproject python_files

Architecture guards that scan test files must derive their scan set from `pyproject.toml`'s `python_files` at run time, not from hardcoded filename prefixes. `tests/architecture/test_no_ignored_active_tests.py` reads `python_files` via `tomllib` + `fnmatch(path.name)`, mirroring `tests/regressions/test_issue_9801_collection.py`. Principle: if pytest doesn't collect it, the guard doesn't scan it — so `tests/_adr_pin_support.py` and `_spawn_audit.py` stay exempt by rule, no allowlist.

**Why:** Hardcoded prefixes miss collected files (103 `regression_*.py` were invisible to ADR-0083's gate) and sweep in non-collected fixtures like `tests/trust/adversarial/cases/.../tests_calc_scratch.py`.
