---
id: "01KR9A3F20M01PGF32CF88W9A5"
name: "MergeStateWatcherLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/merge_state_watcher_loop.py:MergeStateWatcherLoop"
aliases: ["merge state watcher loop", "merge state watcher", "conflict rebase loop"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-06-05T01:03:42.463501+00:00"
---

## Definition

Caretaker loop that periodically scans all open PRs for merge conflicts and auto-rebases or escalates them (ADR-0029). The filter is intentionally broad: RC promotion PRs, Dependabot bumps, agent PRs, and manual PRs all benefit from auto-rebase when they go DIRTY against `main`. PRs already labeled `hydraflow-hitl` (being handled by `PRUnsticker`) or `hydraflow-review` (active reviewer worktree) are skipped to avoid stepping on in-progress work. Delegates the actual conflict-detection and rebase logic to `MergeStateWatcher`.

## Invariants

- Default tick interval is 600 seconds (10 minutes).
- PRs labeled `hydraflow-hitl` or `hydraflow-review` are skipped.
- Kill-switch is via `enabled_cb("merge_state_watcher")` and `config.merge_state_watcher_loop_enabled`.
