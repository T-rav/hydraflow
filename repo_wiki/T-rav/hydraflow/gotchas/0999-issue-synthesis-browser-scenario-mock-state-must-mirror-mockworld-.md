---
id: 0999
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.221861+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# Browser scenario mock state must mirror MockWorld reference stubs

`tests/scenarios/browser/scenarios/test_loops_browser.py` mocks `state` independently from `tests/scenarios/test_loops.py`; when a loop starts reading a new counter, only one may get updated. `_in_retry_window()` in `src/workspace_gc_loop.py` (added by #10459) reads both `get_issue_attempts` and `get_auto_agent_attempts` — the browser test's `MagicMock()` stubbed only the first, causing `TypeError: '<' not supported between int and MagicMock`. Treat `tests/scenarios/test_loops.py` as the source of truth for which state methods a loop under test needs stubbed, and check both scenarios whenever a loop's read surface grows.

**Why:** one-sided mock updates pass locally but break CI only in the scenario nobody re-ran, blocking RC promotion.
