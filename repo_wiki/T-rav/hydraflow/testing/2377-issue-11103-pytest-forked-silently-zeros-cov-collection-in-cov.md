---
id: 2377
topic: testing
source_issue: 11103
source_phase: plan
created_at: 2026-08-14T07:34:32.949674+00:00
status: superseded
corroborations: 1
superseded_by: 2565
---

# pytest --forked silently zeros --cov collection in coverage job

Do not combine `--forked` with `--cov=src` in the `Coverage (trailing)` job. Measured on identical `tests/regressions` files: `--forked --cov=src` collects 1,674 statements (1% total) vs 68,156 (8%) un-forked.

- The `regression` job uses `--forked` safely because it has no coverage floor.
- The coverage job has a live `--cov-fail-under=70`; forking makes regressions contribute ~0 coverage.
- Mirror the Makefile's `make coverage` shape (Makefile:239-241), which runs un-forked.
- A counter-pin in `test_issue_11103.py` asserts no coverage-job step passes `--forked`.

**Why:** Forking subprocesses breaks coverage's in-process collection; the 70% floor either trips or passes while silently under-reporting regression coverage.
