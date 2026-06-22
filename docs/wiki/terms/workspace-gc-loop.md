---
id: "01KT3WKPR5MN8QJ14CF77W6K7"
name: "WorkspaceGCLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/workspace_gc_loop.py:WorkspaceGCLoop"
aliases: ["workspace gc loop", "workspace garbage collector", "worktree gc loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K4"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K8"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01KVHDB0GY6PSQPWY90DH8TNQS"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-20T05:03:15.326246+00:00"
---

## Definition

Background caretaker loop that periodically garbage-collects stale worktrees and orphaned branches. Handles three leak classes: worktrees tracked in `StateTracker` whose PR has been merged or closed, orphaned worktree directories on disk with no `StateTracker` entry, and orphaned remote branches with no open PR. Catches worktrees that leak when PRs are merged manually, via HITL resolution, or when implementations fail or crash mid-cleanup.

## Invariants

- Kill-switch: `enabled_cb("workspace_gc")` AND `config.workspace_gc_loop_enabled` — both must be true to run.
- Caps at `_MAX_GC_PER_CYCLE = 20` collections per tick to avoid long-running passes.
- State removal happens before `WorkspacePort.destroy()` so a crash between the two steps leaves the entry gone; `destroy()` is idempotent.
- An optional `is_in_pipeline_cb` guard prevents GC of issues still being actively processed by a phase.
