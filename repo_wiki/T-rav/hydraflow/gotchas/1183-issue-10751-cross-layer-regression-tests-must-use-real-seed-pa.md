---
id: 1183
topic: gotchas
source_issue: 10751
source_phase: plan
created_at: 2026-07-27T23:15:11.981967+00:00
status: active
corroborations: 1
---

# Cross-layer regression tests must use real seed payloads

Boot-seed regression tests must persist a real error via `BGWorkerManager.update_status`, reboot a real orchestrator, capture real published seed payloads, and run real `vitals.js`/`loops.js` view-models — never hand-written event dicts.

`tests/regressions/test_issue_10751.py` drives both layers end-to-end (skip when node absent). `tests/scenarios/test_boot_seed_replay_scenario.py` uses MockWorld fakes for boot behaviour.

**Why:** A fix in either layer alone can't make the test green by accident when both real layers must agree on the wire shape.
