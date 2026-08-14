---
id: 2464
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.898621+00:00
status: active
corroborations: 1
supersedes: 2274
---

# MockWorld GC scenario: seed protected + collectable issue

Scenario tests for WorkspaceGCLoop must seed both a protected and a collectable issue in the same run, asserting one worktree survives while the other is destroyed in the same pass.

Example: `_seed_ports(world, workspace_gc_state=...)` then `world.run_with_loops(['workspace_gc'], cycles=1)` — always pair a positive and negative case.

**Why:** A guard that's too permissive (never collects) is as much a regression as one that's too aggressive, and only a same-pass dual assertion catches the former.
