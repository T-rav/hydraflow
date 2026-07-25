---
id: 1008
topic: testing
source_issue: 10508
source_phase: plan
created_at: 2026-07-25T04:34:17.689715+00:00
status: active
corroborations: 1
---

# quality target must cap worker pools per-target, not globally

When adding CPU budget vars for `make quality` in `Makefile`, assign them (e.g. `QUALITY_XDIST_WORKERS`, `QUALITY_VITEST_WORKERS`) only on the `quality:` recipe line, never at top-level scope. A top-level assignment gets picked up by `.env`'s `-include`d `export` and throttles `test-ui`, `test`, and CI too.

Example:
- `quality: deps lint-ul` gets `VITEST_MAX_WORKERS=... PYTEST_XDIST_AUTO_NUM_WORKERS=...` prefixed on its own line
- `UI_TEST_CMD`, `PYTEST_PARALLEL`, and CI job definitions stay untouched

**Why:** the six-job `quality` fan-out (`pytest -n auto` + vitest `max(cpus-1,1)`) already oversubscribes 8 cores to ~19 processes; a global cap fixes that but silently slows every other target and CI's Dashboard Build job that expect full-width pools.
