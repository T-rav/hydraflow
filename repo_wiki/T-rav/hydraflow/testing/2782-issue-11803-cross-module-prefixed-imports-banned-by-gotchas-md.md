---
id: 2782
topic: testing
source_issue: 11803
source_phase: plan
created_at: 2026-08-30T09:12:38.105341+00:00
status: active
corroborations: 1
---

# Cross-module `_`-prefixed imports banned by gotchas.md

Public symbols only for cross-module imports; never import a `_`-prefixed name across modules.

When promoting a local helper like `_flow_stopped` to shared `src/flows/guards.py`, name it `flow_stopped` (public). The migration child binds `_flow_stopped = flow_stopped` per phase to preserve `e.when is _flow_stopped` identity assertions in `tests/test_plan_phase_flow.py`.

**Why:** `docs/wiki/gotchas.md` bans cross-module `_`-prefixed imports to enforce module boundaries.
