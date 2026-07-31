---
id: 1718
topic: testing
source_issue: 10860
source_phase: plan
created_at: 2026-07-31T01:48:16.698142+00:00
status: active
corroborations: 1
---

# Nested coverage.Coverage().start() zeroes outer pytest --cov report

Never call `coverage.Coverage().start()` inside a `pytest --cov=src` run. Use a `sys.settrace` probe wrapped around the function under test, saving and restoring `sys.gettrace()`.

Measured in this repo: nested `coverage.Coverage()` yielded 0.00% + `no-data-collected`; `sys.settrace` yielded 6.72% with identical covered line sets.

**Why:** Nesting a collector inside an active `pytest --cov` session zeroes the outer report — the suite stays green while `make coverage` silently reports nothing or passes `fail-under` with stale data.
