---
id: 0910
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.764284+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# Browser scenario mock state must mirror MockWorld reference stubs

`tests/scenarios/browser/scenarios/test_loops_browser.py` mocks `state` independently from `tests/scenarios/test_loops.py`; when a loop starts reading a new counter, only one may get updated. `_in_retry_window()` in `src/workspace_gc_loop.py` (added by #10459) reads both `get_issue_attempts` and `get_auto_agent_attempts` — the browser test's `MagicMock()` stubbed only the first, causing `TypeError: '<' not supported between int and MagicMock`. Treat `tests/scenarios/test_loops.py` as the source of truth for which state methods a loop under test needs stubbed, and check both scenarios whenever a loop's read surface grows.

**Why:** one-sided mock updates pass locally but break CI only in the scenario nobody re-ran, blocking RC promotion.
