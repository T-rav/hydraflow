---
id: 2566
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.586390+00:00
status: active
corroborations: 1
supersedes: 2378
---

# Makefile is canonical for PYTEST_SERIAL_PATHS, not regression job

The Makefile (`PYTEST_SERIAL_PATHS`, ~line 239-241) is the single source of truth for which test paths must run serial. Both the `regression` job's `REAP="..."` list and the coverage job's serial leg must mirror it, but neither is authoritative.

Example: drift guards: `tests/architecture/test_reap_serial_list_sync.py` pins Makefile↔regression-job agreement; `tests/regressions/test_issue_11103.py` pins coverage-job↔Makefile agreement.

**Why:** Three independent definitions of 'serial tests' will drift; pinning to the Makefile prevents a test running parallel in one lane and serial in another.
