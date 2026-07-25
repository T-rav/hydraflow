---
id: 0846
topic: gotchas
source_issue: 10508
source_phase: plan
created_at: 2026-07-25T04:34:17.689762+00:00
status: active
corroborations: 1
---

# quality-recipe regression tests must assert env scoping, not just pool size

`tests/regressions/test_issue_10508.py` and `tests/test_makefile_quality_order.py` should assert both that the CPU budget vars are exported under `quality` AND that `make test-ui`/`make test` see them empty — pool-size assertions alone miss leakage.

Gotcha: a helper like `_make_var("UI_TEST_CMD")` that reads only the first line of a Makefile continued variable will silently pass even if a cap is misplaced inside `UI_TEST_CMD` instead of `vitest.config.mjs` — put the cap in the config file, not the Makefile command string.

**Why:** the fix is only correct if the cap is quality-scoped; a test that only checks worker count can't distinguish a correctly-scoped fix from a global regression.
