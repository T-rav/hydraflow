---
id: 2379
topic: testing
source_issue: 11103
source_phase: plan
created_at: 2026-08-14T07:34:32.949730+00:00
status: superseded
corroborations: 1
superseded_by: 2567
---

# Static-parse regression tests guard CI/Makefile config drift

Files under `tests/regressions/test_issue_*.py` that parse `.github/workflows/ci.yml` and the Makefile as static text — no pytest execution, no network — are the established pattern for pinning CI invariants in this repo.

- `test_issue_11103.py` pins the coverage job's serial set against `PYTEST_SERIAL_PATHS` and `REAP_TESTS`.
- `test_issue_10883.py` pins leg1's `--ignore` set against the `test` job's.
- `tests/architecture/test_reap_serial_list_sync.py` pins Makefile↔regression-job agreement.
- Run all three together as the drift-guard set for the CI/serial-tests area.

**Why:** YAML and Makefile changes bypass import-time checks; static-parse guards catch divergence at test time without running the full suite.
