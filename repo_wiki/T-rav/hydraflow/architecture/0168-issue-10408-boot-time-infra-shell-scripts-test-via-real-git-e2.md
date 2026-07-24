---
id: 0168
topic: architecture
source_issue: 10408
source_phase: plan
created_at: 2026-07-24T05:56:46.873244+00:00
status: active
corroborations: 1
---

# Boot-time infra shell scripts test via real-git e2e, not Port/MockWorld layers

`scripts/run-factory-isolated.sh` is boot-time infra at the actual git/infrastructure edge, not a hexagonal-Port adapter, and it crosses no orchestrator/runner phase — so a `tests/scenarios/` MockWorld scenario and Port routing don't apply, and ADR-0049's kill-switch requirement is N/A. The correct top test layer is a subprocess regression test that runs the extracted sync block against sandboxed real origin/workspace git repos (e.g. `tests/regressions/test_issue_10408.py`), not mocks.

**Why:** applying the standard three-layer pyramid (unit + MockWorld + sandbox e2e) here would add a MockWorld scenario that tests nothing real, since the bug only reproduces against actual git state transitions.
