---
id: 3472
topic: patterns
source_issue: 11321
source_phase: plan
created_at: 2026-08-16T09:00:03.766518+00:00
status: superseded
corroborations: 1
superseded_by: 3618
---

# Rename _-prefixed params when they become load-bearing branches

Rename a `_`-prefixed parameter when it becomes a branching condition; keep it positional-compatible with the base-class signature.

`DiagnosticRunner._build_command` renamed `_worktree` to `worktree` once it branched read-only vs edit-capable, staying positional-compatible with `BaseRunner._build_command`.

**Why:** A `_` prefix signals "unused" — callers would ignore a load-bearing argument.
