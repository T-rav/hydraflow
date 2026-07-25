---
id: 0823
topic: gotchas
source_issue: 10487
source_phase: plan
created_at: 2026-07-24T22:26:43.556423+00:00
status: active
corroborations: 1
---

# Browser scenario mock state must mirror MockWorld reference stubs

`tests/scenarios/browser/scenarios/test_loops_browser.py` mocks `state` independently from `tests/scenarios/test_loops.py`; when a loop starts reading a new counter, only one may get updated. `_in_retry_window()` in `src/workspace_gc_loop.py` (added by #10459) reads both `get_issue_attempts` and `get_auto_agent_attempts` — the browser test's `MagicMock()` stubbed only the first, causing `TypeError: '<' not supported between int and MagicMock`. Treat `tests/scenarios/test_loops.py` as the source of truth for which state methods a loop under test needs stubbed, and check both scenarios whenever a loop's read surface grows.
**Why:** one-sided mock updates pass locally but break CI only in the scenario nobody re-ran, blocking RC promotion.
