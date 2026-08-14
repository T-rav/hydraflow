---
id: 2565
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.568421+00:00
status: active
corroborations: 1
supersedes: 2377
---

# pytest --forked silently zeros --cov collection in coverage job

Do not combine `--forked` with `--cov=src` in the `Coverage (trailing)` job. `--forked --cov=src` collects 1,674 statements (1% total) vs 68,156 (8%) un-forked.

Example: the coverage job has a live `--cov-fail-under=70`; forking makes regressions contribute ~0 coverage. Mirror the Makefile's `make coverage` shape (Makefile:239-241), which runs un-forked. A counter-pin in `test_issue_11103.py` asserts no coverage-job step passes `--forked`.

**Why:** Forking subprocesses breaks coverage's in-process collection; the 70% floor either trips or passes while silently under-reporting regression coverage.
