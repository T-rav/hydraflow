---
id: 2765
topic: testing
source_issue: 11465
source_phase: plan
created_at: 2026-08-20T06:26:27.906032+00:00
status: active
corroborations: 1
---

# Test-only changes skip ADR-0044 MockWorld and ADR-0049

Rule: Test-only PRs that add no orchestrator/runner/phase behavior and no new loop or worker do not trigger ADR-0044 MockWorld scenario requirements or ADR-0049 kill-switch requirements.

The unit test layer is the correct layer for such changes.

**Why:** Applying orchestrator-level quality gates to unit test additions creates false blocking without catching real integration risks, slowing test-only PRs unnecessarily.
