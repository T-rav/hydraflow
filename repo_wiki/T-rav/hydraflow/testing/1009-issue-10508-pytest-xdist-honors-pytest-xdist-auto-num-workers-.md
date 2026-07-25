---
id: 1009
topic: testing
source_issue: 10508
source_phase: plan
created_at: 2026-07-25T04:34:17.689754+00:00
status: active
corroborations: 1
---

# pytest-xdist honors PYTEST_XDIST_AUTO_NUM_WORKERS to bound `-n auto`

To cap `pytest -n auto`'s worker count without touching the `-n auto` invocation itself, set the `PYTEST_XDIST_AUTO_NUM_WORKERS` env var (pytest-xdist >=3.8.0) on the specific Makefile target, not globally.

Used alongside `QUALITY_VITEST_WORKERS` derived from `os.cpu_count()` via the `$(shell python3 -c ...)` idiom already at `Makefile:5`, floored above zero (e.g. `max(2, N//2)`).

**Why:** avoids hardcoding a worker count that breaks on different CI/dev machine core counts, while still letting `-n auto` remain the invocation everywhere else.
