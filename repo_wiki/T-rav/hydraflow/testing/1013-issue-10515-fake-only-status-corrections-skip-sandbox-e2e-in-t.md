---
id: 1013
topic: testing
source_issue: 10515
source_phase: plan
created_at: 2026-07-25T05:40:37.556715+00:00
status: active
corroborations: 1
---

# Fake-only status corrections skip sandbox e2e in the test pyramid

Per docs/standards/testing/README.md's three-layer pyramid, a fix confined to `FakeIssueStore`'s in-memory status vocabulary (no docker/UI wiring change) only needs unit + MockWorld scenario layers — no sandbox e2e. Issue #10515's plan pairs `tests/regressions/test_issue_10515.py` (unit) with `tests/scenarios/test_pipeline_snapshot_terminal_status_scenario.py` (MockWorld) and explicitly omits sandbox e2e with the reasoning documented in Key Considerations.

**Why:** Adding sandbox e2e for a pure data-shape correction would be scope creep against the pyramid's per-layer justification requirement, not added rigor.
