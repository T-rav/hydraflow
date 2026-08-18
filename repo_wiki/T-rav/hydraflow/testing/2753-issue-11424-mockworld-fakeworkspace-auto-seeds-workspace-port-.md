---
id: 2753
topic: testing
source_issue: 11424
source_phase: plan
created_at: 2026-08-18T04:14:44.048812+00:00
status: active
corroborations: 1
---

# MockWorld FakeWorkspace auto-seeds workspace port for free

`MockWorld.run_with_loops` unconditionally sets `_loop_ports["workspace"] = self._workspace`, where `self._workspace` is a `FakeWorkspace` that records create/destroy calls.

Wiring `_build_diagnostic` to forward `workspaces=ports.get("workspace")` makes the `DiagnosticLoop`'s `_workspaces`-gated path reachable in scenarios with no additional fake or seeding helper.

**Why:** Without forwarding, the gated path stays dead — the loop lazily builds a real workspace, hiding unreachable code from scenario coverage.
