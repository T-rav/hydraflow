---
id: 2567
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.591139+00:00
status: active
corroborations: 1
supersedes: 2379
---

# Static-parse regression tests guard CI/Makefile config drift

Files under `tests/regressions/test_issue_*.py` that parse `.github/workflows/ci.yml` and the Makefile as static text — no pytest execution, no network — are the established pattern for pinning CI invariants in this repo.

Example: `test_issue_11103.py` pins the coverage job's serial set; `test_issue_10883.py` pins leg1's `--ignore` set; `tests/architecture/test_reap_serial_list_sync.py` pins Makefile↔regression-job agreement. Run all three together as the drift-guard set.

**Why:** YAML and Makefile changes bypass import-time checks; static-parse guards catch divergence at test time without running the full suite.
